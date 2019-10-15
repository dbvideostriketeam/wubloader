import datetime
import itertools
import logging
import os
import signal

import argh
import gevent.backdoor
import matplotlib.pyplot as plt
from matplotlib import colors
import numpy as np
import prometheus_client as prom

import common


HOUR_FMT = '%Y-%m-%dT%H'

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

		os.mkdir('/coverage_maps')

		while not self.stopping.is_set():

			for quality in self.qualities:
				if self.stopping.is_set():
					break
				path = os.path.join(self.base_dir, self.channel, quality)
				hours = [name for name in os.listdir(path) if not name.startswith('.')]
				hours.sort()
				previous_hour_segments = None
				for hour in hours:
					if self.stopping.is_set():
						break
					self.logger.info('Checking {}/{}'.format(quality, hour))

					# based on common.segments.best_segments_by_start
					# but more complicated to capture more detailed metrics
					hour_path = os.path.join(self.base_dir, self.channel, quality, hour)
					segment_names = [name for name in os.listdir(hour_path) if not name.startswith('.')]

					if not segment_names:
						self.logger.info('{}/{} is empty'.format(quality, hour))
						continue

					segment_names.sort()
					parsed = (common.parse_segment_path(os.path.join(hour_path, name)) for name in segment_names)

					full_segment_count = 0
					partial_segment_count = 0
					full_segment_duration = datetime.timedelta(0)
					partial_segment_duration = datetime.timedelta(0)
					full_repeats = 0
					full_repeat_duration = datetime.timedelta(0)
					partial_repeats = 0
					partial_repeat_duration = datetime.timedelta(0)

					best_segments = []
					holes = []
					editable_holes = []
					overlap_count = 0
					overlap_duration = datetime.timedelta(0)
					previous = None
					previous_editable = None
					coverage = datetime.timedelta(0)
					editable_coverage = datetime.timedelta(0)
					only_partials = []

					for start_time, segments in itertools.groupby(parsed, key=lambda segment: segment.start):
						full_segments = []
						partial_segments = []
						for segment in segments:
							if segment.type == 'full':
								full_segments.append(segment)
								full_segment_count += 1
								full_segment_duration += segment.duration
							elif segment.type == 'partial':
								partial_segments.append(segment)
								partial_segment_count += 1
								partial_segment_duration += segment.duration

						if full_segments:
							if len(full_segments) == 1:
								best_segment = full_segments[0]
							else:
								full_segments.sort(key=lambda segment: (segment.duration))
								best_segment = full_segments[-1]
								for segment in full_segments[:-1]:
									full_repeats += 1
									full_repeat_duration += segment.duration
							if partial_segments:
								for segment in partial_segments:
									partial_repeats += 1
									partial_repeat_duration += segment.duration
						else:
							partial_segments.sort(key=lambda segment: (segment.duration))
							best_segment = partial_segments[-1]
							only_partials.append((best_segment.start, best_segment.start + best_segment.duration))
							for segment in partial_segments[:-1]:
								partial_repeats += 1
								partial_repeat_duration += segment.duration
						self.logger.debug(best_segment.path.split('/')[-1])
						best_segments.append(best_segment)

						# now update coverage, overlaps and holes

						if previous is None:
							coverage += best_segment.duration
							editable_coverage += best_segment.duration
							previous_editable = best_segment

						else:
							previous_end = previous.start + previous.duration
							if segment.start < previous_end:
								overlap_count += 1
								overlap_duration += previous_end - segment.start
								coverage += segment.start - previous_end + segment.duration
							else:
								coverage += segment.duration
								editable_coverage += segment.duration

								if segment.start > previous_end:
									holes.append((previous_end, segment.start))

								previous_editable_end = previous_editable.start + previous_editable.duration
								if segment.start > previous_editable_end:
									editable_holes.append((previous_editable_end, segment.start))

								previous_editable = best_segment

						previous = best_segment

					start = best_segments[0].start
					end = best_segments[-1].start + best_segments[-1].duration
					hole_duration = end - start - coverage
					editable_hole_duration = end - start - editable_coverage

					pixel_starts = np.arange(3600)
					pixel_ends = np.arange(1, 3601)

					runtime_mask = np.ones(3600, dtype=np.bool_)
					coverage_mask = np.ones(3600, dtype=np.bool_)
					partial_mask = np.zeros(3600, dtype=np.bool_)

					hour_start = datetime.datetime.strptime(hour, HOUR_FMT)
					hour_end = hour_start + datetime.timedelta(hours=1)
					# handle the case when there is a hole between the last segment of the previous hour and the first of this
					if previous_hour_segments:
						last_segment = previous_hour_segments[-1]
						if best_segments[0].start > last_segment.start + last_segment.duration:
							holes.append((hour_start, start))
							hole_duration += start - hour_start
							editable_holes.append((hour_start, start))
							editable_hole_duration += start - hour_start							
					# if it is the first hour, instead ignore anything before the first segment
					else:
						start_seconds = start.minute * 60 + start.second
						self.logger.info(start_seconds)
						runtime_mask = runtime_mask & (start_seconds <= pixel_starts)

					#handle the case when there is a hole between the last segment and the end of the hour
					if hour != hours[-1]:
						if end < hour_end:
							holes.append((end, hour_end))
							hole_duration += hour_end - end
							editable_holes.append((end, hour_end))
							editable_hole_duration += hour_end - end							
					# if it is the last hour, ignore anything after the last segment
					else:
						end_seconds = end.minute * 60 + end.second
						self.logger.info(end_seconds)
						runtime_mask = runtime_mask & (end_seconds > pixel_starts)

					for hole in holes:
						hole_start = np.floor((hole[0] - hour_start).seconds)
						hole_end = np.ceil((hole[1] - hour_start).seconds)
						self.logger.info('hole {} {}'.format(hole_start, hole_end))
						coverage_mask = coverage_mask & ((pixel_starts < hole_start) | (pixel_ends > hole_end))

					for partial in only_partials:
						partial_start = np.floor((partial[0] - hour_start).seconds)
						partial_end = np.ceil((partial[1] - hour_start).seconds)
						self.logger.info('partial {} {}'.format(partial_start, partial_end))
						partial_mask = partial_mask | ((pixel_starts >= partial_start) & (pixel_ends <= partial_end))

					runtime_mask = runtime_mask.reshape((60, 60))
					coverage_mask = coverage_mask.reshape((60, 60))
					partial_mask = partial_mask.reshape((60, 60))

					colours = np.ones((60, 60, 3))

					colours[runtime_mask & coverage_mask] = colors.to_rgb('tab:green')
					colours[runtime_mask & partial_mask] = colors.to_rgb('tab:orange')
					colours[runtime_mask & ~coverage_mask] = colors.to_rgb('tab:red')

					fig = plt.figure(figsize=(3, 3))
					fig.add_axes([0, 0, 1, 1])
					plt.imshow(colours)
					plt.axis('off')
					plt.savefig('/coverage_maps/{}.png'.format(hour), dpi=60)


#					plt.figure()
#					plt.imshow(runtime_mask.astype('d'))
#					plt.colorbar()
#					plt.savefig('/coverage_maps/runtime_{}.png'.format(hour))
#
#					plt.figure()
#					plt.imshow(coverage_mask.astype('d'))
#					plt.colorbar()
#					plt.savefig('/coverage_maps/coverage_{}.png'.format(hour))
#
#					plt.figure()
#					plt.imshow(partial_mask.astype('d'))
#					plt.colorbar()
#					plt.savefig('/coverage_maps/partial_{}.png'.format(hour))						

					self.logger.info('{}/{}: Start: {} End: {} ({} s)'.format(quality, hour, start, end, (end - start).seconds))
					self.logger.info('{}/{}: {} full segments totalling {} s'.format(quality, hour, full_segment_count, full_segment_duration.seconds))
					self.logger.info('{}/{}: {} full segment repeats totalling {} s'.format(quality, hour, full_repeats, full_repeat_duration.seconds))
					self.logger.info('{}/{}: {} partial segments totalling {} s'.format(quality, hour, partial_segment_count, partial_segment_duration.seconds))
					self.logger.info('{}/{}: {} partial segment repeats totalling {} s'.format(quality, hour, partial_repeats, partial_repeat_duration.seconds))

					self.logger.info('{}/{}: covering {} s, {} s editable'.format(quality, hour, coverage.seconds, editable_coverage.seconds))
					self.logger.info('{}/{}: {} holes totalling {} s '.format(quality, hour, len(holes), hole_duration.seconds))
					self.logger.info('{}/{}: {} editable holes totalling {} s '.format(quality, hour, len(editable_holes), editable_hole_duration.seconds))
					self.logger.info('{}/{}: {} overlapping segments, {} s overlapping'.format(quality, hour, overlap_count, overlap_duration.seconds))


					previous_hour_segments = best_segments

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
