
import logging
import signal

import gevent.backdoor
import gevent.event
import prometheus_client as prom


class Cutter(object):
	def __init__(self, stop):
		"""Stop is an Event triggering graceful shutdown when set."""
		self.stop = stop
		self.logger = logging.getLogger(type(self).__name__)


	def run(self):
		while not self.stop.is_set():
			pass


class TranscodeChecker(object):
	def __init__(self, stop):
		"""
		Stop is an Event triggering graceful shutdown when set.
		"""
		self.stop = stop
		self.logger = logging.getLogger(type(self).__name__)

	def run(self):
		while not self.stop.is_set():
			pass


def main(metrics_port=8003, backdoor_port=0):
	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	stop = gevent.event.Event()
	gevent.signal(signal.SIGTERM, stop.set) # shut down on sigterm

	logging.info("Starting up")

	# We have two independent jobs to do - to perform cut jobs (cutter),
	# and to check the status of transcoding videos to see if they're done (transcode checker).
	# We want to error if either errors, and shut down if either exits.
	cutter = Cutter(stop)
	transcode_checker = TranscodeChecker(stop)
	jobs = [
		gevent.spawn(cutter.run),
		gevent.spawn(transcode_checker.run),
	]
	# Block until either exits
	gevent.wait(jobs, count=1)
	# Stop the other if it isn't stopping already
	stop.set()
	# Block until both have exited
	gevent.wait(jobs)
	# Call get() for each to re-raise if either errored
	for job in jobs:
		job.get()

	logging.info("Gracefully stopped")
