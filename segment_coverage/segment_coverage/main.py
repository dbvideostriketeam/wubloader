import logging
import os
import signal

import argh
import gevent.backdoor
import prometheus_client as prom

import common



class CoverageChecker(object):
	"""Checks the segment coverage for a given channel in a a given directoy."""

	CHECK_INTERVAL = 60 #seconds between checking coverage

	def __init__(self, channel, qualities, base_dir):
		"""Constructor for CoverageChecker.

		Creates a checker for a given channel with specified qualities."""
		self.base_dir = base_dir
		self.channel = channel
		self.qualities = qualities
		self.stopping = gevent.event.Event()
		self.logger = logging.getLogger('CoverageChecker({})'.format(channel))


	def stop(self):
		"""Stop checking coverage."""
		self.logger.info('Stopping')
		self.stopping.set()


	def run(self):
		"""Loop over available hours for each quality, checking segment coverage."""
		self.logger.info('Starting')

		while not self.stopping.is_set():

			for quality in self.qualities:
				if self.stopping.is_set():
					break
				path = os.path.join(self.base_dir, self.channel, quality)
				hours = [name for name in os.listdir(path) if not name.startswith('.')]
				hours.sort()
				for hour in hours:
					if self.stopping.is_set():
						break
					self.logger.info('Checking {}/{}'.format(quality, hour))
					path = os.path.join(self.base_dir, self.channel, quality, hour)
					segment_names = [name for name in os.listdir(path) if not name.startswith('.')]
					segment_names.sort()
					segments = []
					for name in segment_names:
						path = os.path.join(hour, name)
						try:
							segments.append(common.parse_segment_path(path))
						except ValueError:
							self.logger.warning('Skipping segment {} with invalid format'.format(path))

					full_segments = [segment for segment in segments if segment.type == 'full']
					partial_segments = [segment for segment in segments if segment.type == 'partial']
					full_segments_duration = sum([segment.duration.seconds for segment in full_segments])
					partial_segments_duration = sum([segment.duration.seconds for segment in partial_segments])
					self.logger.info('{}/{}: {} full segments totalling {} s'.format(quality, hour, len(full_segments), full_segments_duration))
					self.logger.info('{}/{}: {} partial segments totalling {} s'.format(quality, hour, len(partial_segments), partial_segments_duration))

			self.stopping.wait(common.jitter(self.CHECK_INTERVAL))



@argh.arg('channels', nargs='*', help='Channels to check coverage of')
@argh.arg('--base-dir', help='Directory where segments are stored. Default is current working directory.')
@argh.arg('--qualities', help="Qualities of each channel to checked. Comma seperated if multiple. Default is 'source'.")
@argh.arg('--metrics-port', help='Port for Prometheus stats. Default is 8006.')
@argh.arg('--backdoor-port', help='Port for gevent.backdoor access. By default disabled.')
def main(channels, base_dir='.', qualities='source', metrics_port=8006,
		backdoor_port=0):
	"""Segment coverage service"""
	qualities = qualities.split(',') if qualities else []
	qualities = [quality.strip() for quality in qualities]

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	managers = []
	workers = []
	for channel in channels:
		logging.info('Starting coverage checks {} with {} as qualities in {}'.format(channel, ', '.join(qualities), base_dir))
		manager = CoverageChecker(channel, qualities, base_dir)
		managers.append(manager)
		workers.append(gevent.spawn(manager.run))

	def stop():
		for manager in managers:
			manager.stop()

	gevent.signal(signal.SIGTERM, stop)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	# Wait for any to die
	gevent.wait(workers, count=1)
	# If one has stopped, either:
	# 1. stop() was called and all are stopping
	# 2. one errored and we should stop all remaining and report the error
	# Our behaviour in both cases is the same:
	# 1. Tell all managers to gracefully stop
	stop()
	# 2. Wait (with timeout) until they've stopped
	gevent.wait(workers)
	# 3. Check if any of them failed. If they did, report it. If mulitple
	#    failed, we report one arbitrarily.
	for worker in workers:
		worker.get()

	logging.info('Gracefully stopped')		
