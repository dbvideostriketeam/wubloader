
import json
import logging
import signal
import socket
from collections import namedtuple

import gevent.backdoor
import gevent.event
import prometheus_client as prom

import common
from common.database import DBManager, query

from .youtube import Youtube


# A list of all the DB column names in CutJob
CUT_JOB_PARAMS = [
	"category",
	"allow_holes",
	"uploader_whitelist",
	"upload_location",
	"video_start",
	"video_end",
	"video_title",
	"video_description",
	"video_channel",
	"video_quality",
]
CutJob = namedtuple('CutJob', [
	"id",
	# the list of segments as returned by get_best_segments()
	"segments",
	# params which map directly from DB columns
] + CUT_JOB_PARAMS)


def format_job(job):
	"""Convert candidate row or CutJob to human-readable string"""
	return "{job.id}({start}/{duration}s {job.video_title!r})".format(
		job=job,
		start=job.video_start.isoformat(),
		duration=(job.video_end - job.video_start).total_seconds(),
	)


class CandidateGone(Exception):
	"""Exception indicating a job candidate is no longer available"""


class Cutter(object):
	def __init__(self, youtube, conn, stop, name, segments_path):
		"""youtube is an authenticated and initialized youtube api client.
		Conn is a database connection.
		Stop is an Event triggering graceful shutdown when set.
		Name is this uploader's unique name.
		Segments path is where to look for segments.
		"""
		self.name = name
		self.youtube = youtube
		self.conn = conn
		self.stop = stop
		self.segments_path = segments_path
		self.logger = logging.getLogger(type(self).__name__)

	def wait(self, interval):
		"""Wait for INTERVAL with jitter, unless we're stopping"""
		self.stop.wait(common.jitter(interval))

	def run(self):
		# clean up any potential bad state from unclean shutdown
		self.rollback_all_owned()
		# main loop - note that the sub-functions are responsible for error handling.
		# any unhandled errors will cause the process to restart and clean up as per rollback_all_owned().
		while not self.stop.is_set():
			job = self.find_candidate()
			try:
				self.claim_job(job)
			except CandidateGone:
				continue
			self.cut_job(job)

	def find_candidate(self):
		"""List EDITED events and find one at random which we have all segments for
		(or for which allow_holes is true), returning a CutJob.
		Polls until one is available.
		"""
		raise NotImplementedError

	def claim_job(self, job):
		"""Update event in DB to say we're working on it.
		If someone beat us to it, or it's changed, raise CandidateGone."""
		# We need to verify all relevant cut params are unchanged, in case they
		# were updated between verifying the candidate and now.
		raise NotImplementedError

	def cut_job(self, job):
		"""Perform the actual cut and upload, taking the job through FINALIZING and into
		TRANSCODING or DONE.
		"""
		raise NotImplementedError

	def rollback_all_owned(self):
		"""Roll back any in-progress jobs that claim to be owned by us,
		to recover from an unclean shutdown."""
		raise NotImplementedError


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


def main(dbconnect, youtube_creds_file, name=None, base_dir=".", metrics_port=8003, backdoor_port=0):
	"""dbconnect should be a postgres connection string, which is either a space-separated
	list of key=value pairs, or a URI like:
		postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE

	youtube_creds_file should be a json file containing keys 'client_id', 'client_secret' and 'refresh_token'.

	name defaults to hostname.
	"""
	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	if name is None:
		name = socket.gethostname()

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
	cutter = Cutter(youtube, dbmanager.get_conn(), stop, name, base_dir)
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
