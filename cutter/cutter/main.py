
import json
import logging
import signal

import gevent.backdoor
import gevent.event
import prometheus_client as prom

import common
from common.database import DBManager, query

from .youtube import Youtube


class Cutter(object):
	def __init__(self, youtube, conn, stop):
		"""youtube is an authenticated and initialized youtube api client.
		Conn is a database connection.
		Stop is an Event triggering graceful shutdown when set.
		"""
		self.youtube = youtube
		self.conn = conn
		self.stop = stop
		self.logger = logging.getLogger(type(self).__name__)


	def run(self):
		while not self.stop.is_set():
			pass


class TranscodeChecker(object):
	NO_VIDEOS_RETRY_INTERVAL = 5
	ERROR_RETRY_INTERVAL = 5

	def __init__(self, youtube, conn, stop):
		"""
		youtube is an authenticated and initialized youtube api client.
		Conn is a database connection.
		Stop is an Event triggering graceful shutdown when set.
		"""
		self.youtube = youtube
		self.conn = conn
		self.stop = stop
		self.logger = logging.getLogger(type(self).__name__)

	def wait(self, interval):
		"""Wait for INTERVAL with jitter, unless we're stopping"""
		self.stop.wait(common.jitter(interval))

	def run(self):
		while not self.stop.is_set():
			try:
				ids = self.get_ids_to_check()
				if not ids:
					self.wait(self.NO_VIDEOS_RETRY_INTERVAL)
					continue
				self.logger.info("Found {} videos in TRANSCODING".format(len(ids)))
				ids = self.check_ids(ids)
				if not ids:
					self.wait(self.NO_VIDEOS_RETRY_INTERVAL)
					continue
				self.logger.info("{} videos are done".format(len(ids)))
				done = self.mark_done(ids)
				self.logger.info("Marked {} videos as done".format(done))
			except Exception:
				self.logger.exception("Error in TranscodeChecker")
				self.wait(self.ERROR_RETRY_INTERVAL)

	def get_ids_to_check(self):
		result = query(self.conn, """
			SELECT id, video_id
			FROM events
			WHERE state = 'TRANSCODING'
		""")
		return {id: video_id for id, video_id in result.fetchall()}

	def check_ids(self, ids):
		# Future work: Set error in DB if video id is not present,
		# and/or try to get more info from yt about what's wrong.
		statuses = self.youtube.get_video_status(ids.values())
		return {
			id: video_id for id, video_id in ids.items()
			if statuses.get(video_id) == 'processed'
		}

	def mark_done(self, ids):
		result = query(self.conn, """
			UPDATE events
			SET state = 'DONE'
			WHERE id = ANY (%s::uuid[]) AND state = 'TRANSCODING'
		""", ids.keys())
		return result.rowcount


def main(dbconnect, youtube_creds_file, metrics_port=8003, backdoor_port=0):
	"""dbconnect should be a postgres connection string, which is either a space-separated
	list of key=value pairs, or a URI like:
		postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE

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
	dbmanager = DBManager(dsn=dbconnect)
	youtube_creds = json.load(open(youtube_creds_file))
	youtube = Youtube(
		client_id=youtube_creds['client_id'],
		client_secret=youtube_creds['client_secret'],
		refresh_token=youtube_creds['refresh_token'],
	)
	cutter = Cutter(youtube, dbmanager.get_conn(), stop)
	transcode_checker = TranscodeChecker(youtube, dbmanager.get_conn(), stop)
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
