
import json
import logging
import signal

import gevent.backdoor
import gevent.event
import prometheus_client as prom

import common

from .youtube import Youtube


class Cutter(object):
	def __init__(self, youtube, stop):
		"""youtube is an authenticated and initialized youtube api client.
		Stop is an Event triggering graceful shutdown when set.
		"""
		self.youtube = youtube
		self.stop = stop
		self.logger = logging.getLogger(type(self).__name__)


	def run(self):
		while not self.stop.is_set():
			pass


class TranscodeChecker(object):
	def __init__(self, youtube, stop):
		"""
		youtube is an authenticated and initialized youtube api client.
		Stop is an Event triggering graceful shutdown when set.
		"""
		self.youtube = youtube
		self.stop = stop
		self.logger = logging.getLogger(type(self).__name__)

	def run(self):
		while not self.stop.is_set():
			pass


def main(youtube_creds_file, metrics_port=8003, backdoor_port=0):
	"""
	youtube_creds_file should be a json file containing keys 'client_id', 'client_secret' and 'refresh_token'.
	"""
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
	youtube_creds = json.load(open(youtube_creds_file))
	youtube = Youtube(
		client_id=youtube_creds['client_id'],
		client_secret=youtube_creds['client_secret'],
		refresh_token=youtube_creds['refresh_token'],
	)
	cutter = Cutter(youtube, stop)
	transcode_checker = TranscodeChecker(youtube, stop)
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
