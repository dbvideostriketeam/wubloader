
import datetime
import json
import logging
import os
import random
import signal
import socket
from collections import namedtuple

import gevent.backdoor
import gevent.event
import prometheus_client as prom
import requests
from psycopg2 import sql

import common
from common.database import DBManager, query
from common.segments import get_best_segments, cut_segments, ContainsHoles

from .upload_locations import Youtube


videos_uploaded  = prom.Counter(
	'videos_uploaded',
	'Number of videos successfully uploaded',
	['video_channel', 'video_quality', 'upload_location']
)

upload_errors  = prom.Counter(
	'upload_errors',
	'Number of errors uploading a video',
	['video_channel', 'video_quality', 'upload_location', 'final_state']
)

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
	NO_CANDIDATES_RETRY_INTERVAL = 1
	ERROR_RETRY_INTERVAL = 5
	RETRYABLE_UPLOAD_ERROR_WAIT_INTERVAL = 5

	def __init__(self, upload_locations, dbmanager, stop, name, segments_path):
		"""upload_locations is a map {location name: upload location backend}
		Conn is a database connection.
		Stop is an Event triggering graceful shutdown when set.
		Name is this uploader's unique name.
		Segments path is where to look for segments.
		"""
		self.name = name
		self.upload_locations = upload_locations
		self.dbmanager = dbmanager
		self.stop = stop
		self.segments_path = segments_path
		self.logger = logging.getLogger(type(self).__name__)
		self.refresh_conn()

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
			if not job:
				# find_candidate() returning None means we're stopping
				continue
			try:
				self.claim_job(job)
			except CandidateGone:
				continue
			self.cut_job(job)

	def refresh_conn(self):
		"""After errors, we reconnect in case the error was connection-related."""
		self.logger.debug("Reconnecting to DB")
		self.conn = self.dbmanager.get_conn()

	def find_candidate(self):
		"""List EDITED events and find one at random which we have all segments for
		(or for which allow_holes is true), returning a CutJob.
		Polls until one is available, or we are stopping (in which case it returns None)
		"""
		while not self.stop.is_set():
			try:
				candidates = self.list_candidates()
			except Exception:
				self.logger.exception("Error while listing candidates")
				self.refresh_conn()
				self.wait(self.ERROR_RETRY_INTERVAL)
				continue
			if candidates:
				self.logger.info("Found {} job candidates".format(len(candidates)))
			# Shuffle the list so that (most of the time) we don't try to claim the same one as other nodes
			random.shuffle(candidates)
			for candidate in candidates:
				try:
					segments = self.check_candidate(candidate)
				except ContainsHoles:
					# TODO metric
					self.logger.info("Ignoring candidate {} due to holes".format(format_job(candidate)))
					continue # bad candidate, let someone else take it or just try again later
				except Exception as e:
					# Unknown error. This is either a problem with us, or a problem with the candidate
					# (or most likely a problem with us that is only triggered by this candidate).
					# In this case we would rather stay running so other jobs can continue to work if possible.
					# But to give at least some feedback, we set the error message on the job
					# if it isn't already.
					self.logger.exception("Failed to check candidate {}, setting error on row".format(format_job(candidate)))
					try:
						# Since this error message is just for humans, we don't go to too large
						# a length to prevent it being put on the row if the row has changed.
						# We just check its state is still EDITING.
						# Any successful claim will clear its error.
						result = query(self.conn, """
							UPDATE events
							SET error = %s
							WHERE id = %s AND state = 'EDITED' AND error IS NULL
						""", id=candidate.id, error='{}: Error while checking candidate: {}'.format(self.name, e))
					except Exception:
						self.logger.exception("Failed to set error for candidate {}, ignoring".format(format_job(candidate)))
						self.refresh_conn()
					else:
						if result.rowcount > 0:
							assert result.rowcount == 1
							self.logger.info("Set error for candidate {}".format(format_job(candidate)))
					self.wait(self.ERROR_RETRY_INTERVAL)
					continue
				if all(segment is None for segment in segments):
					self.logger.info("Ignoring candidate {} as we have no segments".format(format_job(candidate)))
					continue
				return CutJob(segments=segments, **candidate._asdict())
			# No candidates
			self.wait(self.NO_CANDIDATES_RETRY_INTERVAL)

	def list_candidates(self):
		"""Return a list of all available candidates that we might be able to cut."""
		# We only accept candidates if they haven't excluded us by whitelist,
		# and we are capable of uploading to their desired upload location.
		built_query = sql.SQL("""
			SELECT id, {}
			FROM events
			WHERE state = 'EDITED'
			AND (uploader_whitelist IS NULL OR %(name)s = ANY (uploader_whitelist))
			AND upload_location = ANY (%(upload_locations)s)
		""").format(
			sql.SQL(", ").join(sql.Identifier(key) for key in CUT_JOB_PARAMS)
		)
		result = query(self.conn, built_query, name=self.name, upload_locations=self.upload_locations.keys())
		return result.fetchall()

	def check_candidate(self, candidate):
		return get_best_segments(
			os.path.join(self.segments_path, candidate.video_channel, candidate.video_quality),
			candidate.video_start,
			candidate.video_end,
			allow_holes=candidate.allow_holes,
		)

	def claim_job(self, job):
		"""Update event in DB to say we're working on it.
		If someone beat us to it, or it's changed, raise CandidateGone."""
		# We need to verify all relevant cut params are unchanged, in case they
		# were updated between verifying the candidate and now.
		built_query = sql.SQL("""
			UPDATE events
			SET state = 'CLAIMED', uploader = %(name)s, error = NULL
			WHERE id = %(id)s
			AND state = 'EDITED'
			AND {}
		""").format(
			# A built AND over all CUT_JOB_PARAMS to check key = %(key)s.
			# Note the use of IS NOT DISTINCT FROM because key = NULL is false if key is NULL.
			sql.SQL(' AND ').join(
				sql.SQL("{} IS NOT DISTINCT FROM {}").format(sql.Identifier(key), sql.Placeholder(key))
				for key in CUT_JOB_PARAMS
			)
		)
		try:
			result = query(self.conn, built_query, name=self.name, **job._asdict())
		except Exception:
			# Rather than retry on failure here, just assume someone else claimed it in the meantime
			self.logger.exception("Error while claiming job {}, aborting claim".format(format_job(job)))
			self.refresh_conn()
			self.wait(self.ERROR_RETRY_INTERVAL)
			raise CandidateGone
		if result.rowcount == 0:
			self.logger.info("Failed to claim job {}".format(format_job(job)))
			raise CandidateGone
		self.logger.info("Claimed job {}".format(format_job(job)))
		assert result.rowcount == 1

	def cut_job(self, job):
		"""Perform the actual cut and upload, taking the job through FINALIZING and into
		TRANSCODING or DONE.

		Handles various error conditions:
		* Errors while cutting: Assumed to be non-retryable until cut parameters are changed
		  by operator. Sets error and rolls back to UNEDITED.
		* Request error before request body closed: Assumed to be a transient network failure,
		  immediately retryable. Sets error and rolls back to EDITED.
		* Request error after request body closed: It's unknown whether the request went through.
		  Sets error and remains in FINALIZING. Operator intervention is required.
		* Row has changed (no longer claimed by us) before request body closed:
		  Assumed an operator has made changes and changed state back. Abort cutting without error.
		* Row has changed (no longer claimed by us) after request body closed:
		  Request has already gone through, but we failed to update database with this state.
		  Causes program crash (JobConsistencyError) and restart,
		  at which point it will re-sync with DB as best it can.
		  This situation almost certainly requires operator intervention.
		"""

		upload_backend = self.upload_locations[job.upload_location]
		self.logger.info("Cutting and uploading job {} to {}".format(format_job(job), upload_backend))
		cut = cut_segments(job.segments, job.video_start, job.video_end)

		# This flag tracks whether we've told requests to finalize the upload,
		# and serves to detect whether errors from the request call are recoverable.
		# Wrapping it in a one-element list is a hack that lets us modify it from within
		# a closure (as py2 lacks the nonlocal keyword).
		finalize_begun = [False]

		# This dummy exception is used to pass control flow back out of upload_wrapper
		# if we've already handled the error and do not need to do anything further.
		class ErrorHandled(Exception):
			pass

		# This exception indicates a job we thought was ours somehow disappeared
		# while we were still trying to cut it. This most likely represents a logic error
		# or that our instance is in a bad state, and will be raised up to run() to terminate
		# the cutter entirely.
		class JobConsistencyError(Exception):
			pass

		def set_row(**kwargs):
			"""Set columns on the row being cut. Returns True on success,
			False if row could not be found.
			Example:
				if not set_row(state='UNEDITED', error=e):
					<handle row having gone missing>
			"""
			# construct an UPDATE query like "SET key1=%(key1)s, key2=%(key2)s, ..."
			built_query = sql.SQL("""
				UPDATE events
				SET {}
				WHERE id = %(id)s AND uploader = %(name)s
			""").format(sql.SQL(", ").join(
				sql.SQL("{} = {}").format(
					sql.Identifier(key), sql.Placeholder(key),
				) for key in kwargs
			))
			result = query(self.conn, built_query, id=job.id, name=self.name, **kwargs)
			return result.rowcount == 1

		def upload_wrapper():
			# This generator wraps the cut_segments generator so we can
			# do things in between the data being finished and finalizing the request.
			# This is also where we do the main error handling.

			try:
				for chunk in cut:
					yield chunk
			except Exception as ex:
				self.logger.exception("Error occurred while trying to cut job {}".format(format_job(job)))
				# Assumed error is not retryable, set state back to UNEDITED and set error.
				if not set_row(state='UNEDITED', error="Error while cutting: {}".format(ex), uploader=None):
					self.logger.warning("Tried to roll back row {} to unedited but it was already cancelled.".format(job.id))
				upload_errors.labels(video_channel=job.video_channel,
						video_quality=job.video_quality,
						upload_location=job.upload_location,
						final_state='UNEDITED').inc()
				# Abort the cut without further error handling
				raise ErrorHandled

			# The data is now fully uploaded, but the request is not finalized.
			# We now set the DB state to finalized so we know about failures during this
			# critical section.

			self.logger.debug("Setting job to finalizing")
			if not set_row(state='FINALIZING'):
				# Abort the cut and crash the program, forcing a state resync
				raise JobConsistencyError(
					"No job with id {} and uploader {} when setting FINALIZING"
					.format(job.id, self.name)
				)
			finalize_begun[0] = True

			# Now we return from this generator, and any errors between now and returning
			# from requests.post() are not recoverable.

		try:
			video_id = upload_backend.upload_video(
				title=job.video_title,
				description=job.video_description,
				tags=[], # TODO
				data=upload_wrapper(),
				hidden=True, # TODO remove when not testing
			)
		except JobConsistencyError:
			raise # this ensures it's not caught in the next except block
		except ErrorHandled:
			# we're aborting the cut, error handling has already happened
			return
		except Exception as ex:
			self.refresh_conn()

			# for HTTPErrors, getting http response body is also useful
			if isinstance(ex, requests.HTTPError):
				ex = "{}: {}".format(ex, ex.response.content)

			# if error during finalizing, set it in the database and leave it
			# stuck in FINALIZING state for operator intervention.
			if finalize_begun[0]:
				self.logger.critical((
					"Error occurred while finalizing upload of job {}. "
					"You will need to check the state of the video manually."
				).format(format_job(job)))
				error = (
					"An error occurred during FINALIZING, please determine if video was actually "
					"uploaded or not and either move to TRANSCODING/DONE and populate video_id or rollback "
					"to EDITED and clear uploader. "
					"Error: {}"
				).format(ex)
				upload_errors.labels(video_channel=job.video_channel,
						video_quality=job.video_quality,
						upload_location=job.upload_location,
						final_state='FINALIZING').inc()
				if not set_row(error=error):
					# Not only do we not know if it was uploaded, we also failed to set that in the database!
					raise JobConsistencyError(
						"No job with id {} and uploader {} when setting error while finalizing!"
						.format(job.id, self.name)
					)
				return

			# error before finalizing, assume it's a network issue / retryable.
			# set back to EDITED but still set error
			self.logger.exception("Retryable error when uploading job {}".format(format_job(job)))
			upload_errors.labels(video_channel=job.video_channel,
					video_quality=job.video_quality,
					upload_location=job.upload_location,
					final_state='EDITED').inc()			
			if not set_row(state='EDITED', error="Retryable error while uploading: {}".format(ex), uploader=None):
				raise JobConsistencyError(
					"No job with id {} and uploader {} when setting error while rolling back for retryable error"
					.format(job.id, self.name)
				)
			# pause briefly so we don't immediately grab the same one again in a rapid retry loop
			gevent.sleep(self.RETRYABLE_UPLOAD_ERROR_WAIT_INTERVAL)
			return

		# Success! Set TRANSCODING or DONE and clear any previous error.
		success_state = 'TRANSCODING' if upload_backend.needs_transcode else 'DONE'
		link = "https://youtu.be/{}".format(video_id)
		if not set_row(state=success_state, video_id=video_id, video_link=link, error=None):
			# This will result in it being stuck in FINALIZING, and an operator will need to go
			# confirm it was really uploaded.
			raise JobConsistencyError(
				"No job with id {} and uploader {} when setting to {}"
				.format(job.id, self.name, success_state)
			)

		self.logger.info("Successfully cut and uploaded job {} as {}".format(format_job(job), link))
		videos_uploaded.labels(video_channel=job.video_channel,
				video_quality=job.video_quality,
				upload_location=job.upload_location).inc()

	def rollback_all_owned(self):
		"""Roll back any in-progress jobs that claim to be owned by us,
		to recover from an unclean shutdown."""
		result = query(self.conn, """
			UPDATE events
			SET state = 'EDITED', uploader = NULL
			WHERE state = 'CLAIMED' AND uploader = %(name)s
		""", name=self.name)
		if result.rowcount > 0:
			self.logger.warning("Rolled back {} CLAIMED rows for {} - unclean shutdown?".format(
				result.rowcount, self.name,
			))

		# Also mark any rows in FINALIZED owned by us as errored, these require manual intervention
		result = query(self.conn, """
			UPDATE events
			SET error = %(error)s
			WHERE state = 'FINALIZING' AND uploader = %(name)s AND error IS NULL
		""", name=self.name, error=(
			"Uploader died during FINALIZING, please determine if video was actually "
			"uploaded or not and either move to TRANSCODING/DONE and populate video_id or rollback "
			"to EDITED and clear uploader."
		))
		if result.rowcount > 0:
			self.logger.error("Found {} FINALIZING rows for {}, marked as errored".format(
				result.rowcount, self.name,
			))



class TranscodeChecker(object):
	NO_VIDEOS_RETRY_INTERVAL = 5 # can be fast because it's just a DB lookup
	FOUND_VIDEOS_RETRY_INTERVAL = 20
	ERROR_RETRY_INTERVAL = 20

	def __init__(self, backend, dbmanager, stop):
		"""
		backend is an upload backend that supports transcoding
		and defines check_status().
		Conn is a database connection.
		Stop is an Event triggering graceful shutdown when set.
		"""
		self.backend = backend
		self.dbmanager = dbmanager
		self.stop = stop
		self.logger = logging.getLogger(type(self).__name__)

	def wait(self, interval):
		"""Wait for INTERVAL with jitter, unless we're stopping"""
		self.stop.wait(common.jitter(interval))

	def run(self):
		self.conn = self.dbmanager.get_conn()
		while not self.stop.is_set():
			try:
				ids = self.get_ids_to_check()
				if not ids:
					self.wait(self.NO_VIDEOS_RETRY_INTERVAL)
					continue
				self.logger.info("Found {} videos in TRANSCODING".format(len(ids)))
				ids = self.check_ids(ids)
				if ids:
					self.logger.info("{} videos are done".format(len(ids)))
					done = self.mark_done(ids)
					self.logger.info("Marked {} videos as done".format(done))
				self.wait(self.FOUND_VIDEOS_RETRY_INTERVAL)
			except Exception:
				self.logger.exception("Error in TranscodeChecker")
				# To ensure a fresh slate and clear any DB-related errors, get a new conn on error.
				# This is heavy-handed but simple and effective.
				self.conn = self.dbmanager.get_conn()
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
		done = self.backend.check_status(ids.values())
		return {
			id: video_id for id, video_id in ids.items()
			if video_id in done
		}

	def mark_done(self, ids):
		result = query(self.conn, """
			UPDATE events
			SET state = 'DONE', upload_time = %s
			WHERE id = ANY (%s::uuid[]) AND state = 'TRANSCODING'
		""", datetime.datetime.utcnow(), ids.keys())
		return result.rowcount


def main(dbconnect, config, creds_file, name=None, base_dir=".", metrics_port=8003, backdoor_port=0):
	"""dbconnect should be a postgres connection string, which is either a space-separated
	list of key=value pairs, or a URI like:
		postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE

	config should be a json blob mapping upload location names to a config object
	for that location. This config object should contain the keys:
		type:
			the name of the upload backend type
		no_transcode_check:
			bool. If true, won't check for when videos are done transcoding.
			This is useful when multiple upload locations actually refer to the
			same place just with different settings, and you only want one of them
			to actually do the check.
	along with any additional config options defined for that backend type.

	creds_file should contain any required credentials for the upload backends, as JSON.

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
	dbmanager = None
	stopping = gevent.event.Event()
	while dbmanager is None:
		try:
			dbmanager = DBManager(dsn=dbconnect)
		except Exception:
			delay = common.jitter(10)
			logging.info('Cannot connect to database. Retrying in {:.0f} s'.format(delay))
			stop.wait(delay)

	with open(creds_file) as f:
		credentials = json.load(f)

	config = json.loads(config)
	upload_locations = {}
	needs_transcode_check = []
	for location, backend_config in config.items():
		backend_type = backend_config.pop('type')
		no_transcode_check = backend_config.pop('no_transcode_check', False)
		if type == 'youtube':
			backend_type = Youtube
		else:
			raise ValueError("Unknown upload backend type: {!r}".format(type))
		backend = backend_type(credentials, **backend_config)
		upload_locations[location] = backend
		if backend.needs_transcode and not no_transcode_check:
			needs_transcode_check.append(backend)

	cutter = Cutter(upload_locations, dbmanager, stop, name, base_dir)
	transcode_checkers = [
		TranscodeChecker(backend, dbmanager, stop)
		for backend in needs_transcode_check
	]
	jobs = [gevent.spawn(cutter.run)] + [
		gevent.spawn(transcode_checker.run)
		for transcode_checker in transcode_checkers
	]
	# Block until any one exits
	gevent.wait(jobs, count=1)
	# Stop the others if they aren't stopping already
	stop.set()
	# Block until all have exited
	gevent.wait(jobs)
	# Call get() for each one to re-raise if any errored
	for job in jobs:
		job.get()

	logging.info("Gracefully stopped")
