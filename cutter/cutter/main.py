
import datetime
import hashlib
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
from common.database import DBManager, query, get_column_placeholder
from common.segments import get_best_segments, archive_cut_segments, fast_cut_segments, full_cut_segments, smart_cut_segments, extract_frame, ContainsHoles, get_best_segments_for_frame
from common.images import compose_thumbnail_template, get_template
from common.stats import timed
from common import zulip

from .upload_backends import Youtube, Local, LocalArchive, UploadError


videos_uploaded = prom.Counter(
	'videos_uploaded',
	'Number of videos successfully uploaded',
	['video_channel', 'video_quality', 'upload_location']
)

upload_errors = prom.Counter(
	'upload_errors',
	'Number of errors uploading a video',
	['video_channel', 'video_quality', 'upload_location', 'final_state']
)

no_candidates = prom.Counter(
	'no_candidates',
	"Number of times we looked for candidate jobs but didn't find any",
)

videos_transcoding = prom.Gauge(
	'videos_transcoding',
	"Number of videos currently in transcoding",
	['location'],
)

videos_marked_done = prom.Counter(
	'videos_marked_done',
	"Number of videos we have successfully marked as done",
	['location'],
)

# A list of all the DB column names in CutJob
CUT_JOB_PARAMS = [
	"sheet_name",
	"category",
	"allow_holes",
	"uploader_whitelist",
	"upload_location",
	"public",
	"video_ranges",
	"video_transitions",
	"video_title",
	"video_description",
	"video_tags",
	"video_channel",
	"video_quality",
	"thumbnail_mode",
	"thumbnail_time",
	"thumbnail_template",
	"thumbnail_image",
	"thumbnail_crop",
	"thumbnail_location",
]
CutJob = namedtuple('CutJob', [
	"id",
	# for each range, the list of segments as returned by get_best_segments()
	"segment_ranges",
	# if any, the segments we need to create a thumbnail from
	"thumbnail_segments",
	# params which map directly from DB columns
] + CUT_JOB_PARAMS)

def get_duration(job):
	"""Get total video duration of a job, in seconds"""
	# Due to ranges and transitions, this is actually non-trivial to calculate.
	# Each range overlaps the previous by duration, so we add all the ranges
	# then subtract all the durations.
	without_transitions = sum([
		(range.end - range.start).total_seconds()
		for range in job.video_ranges
	])
	overlap = sum([
		transition.duration
		for transition in job.video_transitions
		if transition is not None
	])
	return without_transitions - overlap


def format_job(job):
	"""Convert candidate row or CutJob to human-readable string"""
	return "{job.id}({start}/{duration}s {job.video_title!r})".format(
		job=job,
		start=job.video_ranges[0].start.isoformat(),
		duration=get_duration(job),
	)


class CandidateGone(Exception):
	"""Exception indicating a job candidate is no longer available"""


class JobCancelled(Exception):
	"""Exception indicating a job was cancelled by an operator after we had claimed it."""


class Cutter(object):
	NO_CANDIDATES_RETRY_INTERVAL = 1
	ERROR_RETRY_INTERVAL = 5
	RETRYABLE_UPLOAD_ERROR_WAIT_INTERVAL = 5

	def __init__(self, upload_locations, dbmanager, stop, name, segments_path, tags, uploader_explicit_only=False):
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
		self.tags = tags
		self.uploader_explicit_only = uploader_explicit_only
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
			try:
				self.cut_job(job)
			except JobCancelled:
				self.logger.info("Job was cancelled while we were cutting it: {}".format(format_job(job)))

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

				def set_error(error):
					"""Common code for the two paths below, for setting an error on the row for humans to see"""
					try:
						# Since this error message is just for humans, we don't go to too large
						# a length to prevent it being put on the row if the row has changed.
						# We just check its state is still EDITING.
						# Any successful claim will clear its error.
						result = query(self.conn, """
							UPDATE events
							SET error = %(error)s
							WHERE id = %(id)s AND state = 'EDITED' AND error IS NULL
						""", id=candidate.id, error=error)
					except Exception:
						self.logger.exception("Failed to set error for candidate {}, ignoring".format(format_job(candidate)))
						self.refresh_conn()
					else:
						if result.rowcount > 0:
							assert result.rowcount == 1
							self.logger.info("Set error for candidate {}".format(format_job(candidate)))

				try:
					segment_ranges, thumbnail_segments = self.check_candidate(candidate)
				except ContainsHoles:
					self.logger.info("Ignoring candidate {} due to holes".format(format_job(candidate)))
					set_error(
						"Node {} does not have all the video needed to cut this row. "
						"This may just be because it's too recent and the video hasn't been downloaded yet. "
						"However, it might also mean that there is a 'hole' of missing video, perhaps "
						"because the stream went down or due to downloader issues. If you know why this "
						"is happening and want to cut the video anyway, re-edit with the 'Allow Holes' option set. "
						"However, even with 'Allow Holes', this will still fail if any range of video is missing entirely."
					.format(self.name))
					continue # bad candidate, let someone else take it or just try again later
				except Exception as e:
					# Unknown error. This is either a problem with us, or a problem with the candidate
					# (or most likely a problem with us that is only triggered by this candidate).
					# In this case we would rather stay running so other jobs can continue to work if possible.
					# But to give at least some feedback, we set the error message on the job
					# if it isn't already.
					self.logger.exception("Failed to check candidate {}, setting error on row".format(format_job(candidate)))
					set_error('{}: Error while checking candidate: {}'.format(self.name, e))
					self.wait(self.ERROR_RETRY_INTERVAL)
					continue

				return CutJob(segment_ranges=segment_ranges, thumbnail_segments=thumbnail_segments, **candidate._asdict())

			# No candidates
			no_candidates.inc()
			self.wait(self.NO_CANDIDATES_RETRY_INTERVAL)

	@timed()
	def list_candidates(self):
		"""Return a list of all available candidates that we might be able to cut."""
		# We only accept candidates if they haven't excluded us by whitelist,
		# and we are capable of uploading to their desired upload location.
		uploader_condition = "(uploader_whitelist IS NULL OR %(name)s = ANY (uploader_whitelist))"
		if self.uploader_explicit_only:
			uploader_condition = "%(name)s = ANY (uploader_whitelist)"
		built_query = sql.SQL("""
			SELECT id, {}
			FROM events
			WHERE state = 'EDITED'
			AND {}
			AND upload_location = ANY (%(upload_locations)s)
		""").format(
			sql.SQL(", ").join(sql.Identifier(key) for key in CUT_JOB_PARAMS),
			sql.SQL(uploader_condition),
		)
		result = query(self.conn, built_query, name=self.name, upload_locations=list(self.upload_locations.keys()))
		return result.fetchall()

	@timed(
		video_channel = lambda ret, self, job: job.video_channel,
		video_quality = lambda ret, self, job: job.video_quality,
		range_count = lambda ret, self, job: len(job.video_ranges),
		normalize = lambda ret, self, job: get_duration(job),
	)
	def check_candidate(self, candidate):
		# Gather segment lists. Abort early if we find a range for which we have no segments at all.
		hours_path = os.path.join(self.segments_path, candidate.video_channel, candidate.video_quality)
		segment_ranges = []
		for range in candidate.video_ranges:
			segments = get_best_segments(
				hours_path,
				range.start,
				range.end,
				allow_holes=candidate.allow_holes,
			)
			if segments == [None]:
				raise ContainsHoles
			segment_ranges.append(segments)
		# Also check the thumbnail time if we need to generate it
		thumbnail_segments = None
		if candidate.thumbnail_mode in ('BARE', 'TEMPLATE') and candidate.thumbnail_image is None:
			thumbnail_segments = get_best_segments_for_frame(hours_path, candidate.thumbnail_time)
			if thumbnail_segments == [None]:
				raise ContainsHoles
		return segment_ranges, thumbnail_segments

	@timed(
		video_channel = lambda ret, self, job: job.video_channel,
		video_quality = lambda ret, self, job: job.video_quality,
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
				sql.SQL("{} IS NOT DISTINCT FROM {}").format(sql.Identifier(key), get_column_placeholder(key))
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
		* Errors generating thumbnail: Assumed to be non-retryable until thumbnail parameters
		  are changed by operator. Sets error and rolls back to UNEDITED.
		* Errors while cutting: Assumed to be non-retryable until cut parameters are changed
		  by operator. Sets error and rolls back to UNEDITED.
		* Request error before request body closed: Assumed to be a transient network failure,
		  immediately retryable. Sets error and rolls back to EDITED.
		* Request error after request body closed: It's unknown whether the request went through.
		  Sets error and remains in FINALIZING. Operator intervention is required.
		* Request error when setting thumbnail: Assumed to be a transient network failure,
		  but the video was already uploaded. So we can't set back to EDITED. Instead, we set error
		  error and set state to MODIFIED, indicating the video's state and the database are out
		  of sync. Since MODIFIED rows with an error are not processed, an operator will need to
		  dismiss the error before continuing.
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

		# This flag tracks the state of the upload request:
		# * 'not finished'
		# * 'finishing'
		# * 'finished'
		# and serves to detect whether errors from the request call are recoverable.
		upload_finished = 'not finished'

		# This exception indicates a job we thought was ours somehow disappeared
		# while we were still trying to cut it. This most likely represents a logic error
		# or that our instance is in a bad state, and will be raised up to run() to terminate
		# the cutter entirely.
		class JobConsistencyError(Exception):
			pass

		def set_row(**kwargs):
			"""Set columns on the row being cut. Raises JobConsistencyError on failure.
			Example: set_row(state='UNEDITED', error=e)
			"""
			# construct an UPDATE query like "SET key1=%(key1)s, key2=%(key2)s, ..."
			built_query = sql.SQL("""
				UPDATE events
				SET {}
				WHERE id = %(id)s AND uploader = %(name)s
			""").format(sql.SQL(", ").join(
				sql.SQL("{} = {}").format(
					sql.Identifier(key), get_column_placeholder(key),
				) for key in kwargs
			))
			result = query(self.conn, built_query, id=job.id, name=self.name, **kwargs)
			if result.rowcount != 1:
				# If we hadn't yet finished the upload, then this means an operator cancelled the job
				# while we were cutting it. This isn't a problem.
				if upload_finished == 'not finished':
					raise JobCancelled()
				raise JobConsistencyError("No job with id {} and uploader {} when setting: {}".format(
					job.id, self.name, ", ".join("{} = {!r}".format(k, v) for k, v in kwargs.items())
				))

		def upload_wrapper():
			# This generator wraps the cut_segments generator so we can
			# do things in between the data being finished and finalizing the request.
			# This is also where we do the main error handling.

			# Tell python to use the upload_finished variable from the enclosing scope,
			# instead of creating a new (shadowing) variable which is the default when
			# you do "variable = value".
			nonlocal upload_finished

			try:
				if upload_backend.encoding_settings in ("fast", "smart"):
					self.logger.debug(f"Using {upload_backend.encoding_settings} cut")
					cut_fn = {
						"fast": fast_cut_segments,
						"smart": smart_cut_segments,
					}[upload_backend.encoding_settings]
					cut = cut_fn(job.segment_ranges, job.video_ranges, job.video_transitions)
				elif upload_backend.encoding_settings == "archive":
					self.logger.debug("Using archive cut")
					if any(transition is not None for transition in job.video_transitions):
						raise ValueError("Archive cuts do not support complex transitions")
					# Note archive cuts return a list of filenames instead of data chunks.
					# We assume the upload location expects this.
					# We use segments_path as a tempdir path under the assumption that:
					# a) it has plenty of space
					# b) for a Local upload location, it will be on the same filesystem as the
					#    final desired path.
					cut = archive_cut_segments(job.segment_ranges, job.video_ranges, self.segments_path)
				else:
					self.logger.debug("Using encoding settings for {} cut: {}".format(
						"streamable" if upload_backend.encoding_streamable else "non-streamable",
						upload_backend.encoding_settings,
					))
					cut = full_cut_segments(
						job.segment_ranges, job.video_ranges, job.video_transitions,
						upload_backend.encoding_settings, stream=upload_backend.encoding_streamable,
					)

				for chunk in cut:
					yield chunk
			except Exception as ex:
				self.logger.exception("Error occurred while trying to cut job {}".format(format_job(job)))
				# Assumed error is not retryable. Exception chaining preserves original error message.
				raise UploadError("Unhandled exception while cutting", retryable=False) from ex

			# The data is now fully uploaded, but the request is not finalized.
			# We now set the DB state to finalized so we know about failures during this
			# critical section.

			self.logger.debug("Setting job to finalizing")
			set_row(state='FINALIZING')
			upload_finished = 'finishing'

			# Now we return from this generator, and any unknown errors between now and returning
			# from the upload backend are not recoverable.

		def generate_thumbnail():
			# no need to generate if it already exists, or no thumbnail is desired
			if job.thumbnail_mode == 'NONE':
				return None
			if job.thumbnail_image is not None:
				return job.thumbnail_image

			frame = extract_frame(job.thumbnail_segments, job.thumbnail_time)
			# collect chunks into one bytestring as we need to use it multiple times
			frame = b''.join(frame)

			if job.thumbnail_mode == 'BARE':
				image_data = frame
			elif job.thumbnail_mode == 'TEMPLATE':
				template, crop, location = get_template(self.dbmanager, job.thumbnail_template, job.thumbnail_crop, job.thumbnail_location)
				self.logger.info('Generating thumbnail from the video frame at {} using {} as template'.format(job.thumbnail_time, job.thumbnail_template))
				image_data = compose_thumbnail_template(template, frame, crop, location)
			else:
				# shouldn't be able to happen given database constraints
				assert False, "Bad thumbnail mode: {}".format(job.thumbnail_mode)

			# Save what we've generated to the database now, easier than doing it later
			# and might save some effort if we need to retry.
			set_row(thumbnail_image=image_data)
			return image_data

		try:
			# Get thumbnail image, generating it if needed
			try:
				thumbnail = generate_thumbnail()
			except Exception as ex:
				self.logger.exception("Error occurred while trying to generate thumbnail for job {}".format(format_job(job)))
				# Assumed error is not retryable
				raise UploadError("Error while generating thumbnail: {}".format(ex), retryable=False)

			if thumbnail is not None and len(thumbnail) > 2 * 2**20:
				self.logger.warning("Aborting upload as thumbnail is too big ({}MB, max 2MB)".format(len(thumbnail) / 2.**20))
				raise UploadError("Thumbnail is too big ({}MB, max 2MB)".format(len(thumbnail) / 2.**20), retryable=False)

			# UploadErrors in the except block below should be caught
			# the same as UploadErrors in the main try block, so we wrap
			# a second try around the whole thing.
			try:
				video_id, video_link = upload_backend.upload_video(
					title=job.video_title,
					description=job.video_description,
					# Merge static and video-specific tags
					tags=list(set(self.tags + job.video_tags)),
					public=job.public,
					data=upload_wrapper(),
				)
				upload_finished = 'finished'
				if thumbnail is not None:
					upload_backend.set_thumbnail(video_id, thumbnail)
			except (JobConsistencyError, JobCancelled, UploadError):
				raise # this ensures these aren't not caught in the except Exception block
			except Exception as ex:
				self.refresh_conn()

				# for HTTPErrors, getting http response body is also useful
				if isinstance(ex, requests.HTTPError):
					ex = "{}: {}".format(ex, ex.response.content)

				if upload_finished == 'not finished':
					# error before finalizing, assume it's a network issue / retryable.
					self.logger.exception("Retryable error when uploading job {}".format(format_job(job)))
					raise UploadError("Unhandled error in upload: {}".format(ex), retryable=True)

				elif upload_finished == 'finished':
					# error after finalizing, ie. during thumbnail upload.
					# put the video in MODIFIED to indicate it's out of sync, but set error
					# so an operator will check what happened before correcting it.
					self.logger.exception("Error setting thumbnail in job {}".format(format_job(job)))
					upload_errors.labels(
						video_channel=job.video_channel,
						video_quality=job.video_quality,
						upload_location=job.upload_location,
						final_state='MODIFIED',
					).inc()
					set_row(
						state='MODIFIED',
						upload_time=datetime.datetime.utcnow(),
						last_modified=datetime.datetime.utcnow(),
						video_id=video_id,
						video_link=video_link,
						error="Error setting thumbnail: {}".format(ex),
					)
					return

				elif upload_finished == 'finishing':
					# unknown error during finalizing, set it in the database and leave it
					# stuck in FINALIZING state for operator intervention.
					self.logger.critical((
						"Error occurred while finalizing upload of job {}. "
						"You will need to check the state of the video manually."
					).format(format_job(job)), exc_info=True)
					error = (
						"An error occurred during FINALIZING, please determine if video was actually "
						"uploaded or not and either move to TRANSCODING/DONE and populate video_id or rollback "
						"to EDITED and clear uploader. "
						"Error: {}"
					).format(ex)
					upload_errors.labels(
						video_channel=job.video_channel,
						video_quality=job.video_quality,
						upload_location=job.upload_location,
						final_state='FINALIZING',
					).inc()
					set_row(error=error)
					return

				else:
					assert False, "Bad upload_finished value: {!r}".format(upload_finished)

		except UploadError as ex:
			# At this stage, we assume whatever raised UploadError has already
			# logged about it. We're just setting the database as appropriate.
			# If it's retryable, we clear uploader and set back to EDITED.
			# If it isn't, we don't clear uploader (so we know where it failed)
			# and we set it back to UNEDITED, waiting for an editor to manually retry.
			if ex.retryable:
				state = 'EDITED'
				kwargs = {'uploader': None}
			else:
				state = 'UNEDITED'
				kwargs = {}
			self.logger.exception("Upload error for job {}: {}".format(format_job(job), ex))
			upload_errors.labels(
				video_channel=job.video_channel,
				video_quality=job.video_quality,
				upload_location=job.upload_location,
				final_state=state,
			).inc()
			set_row(state=state, error=str(ex), **kwargs)
			if ex.retryable:
				# pause briefly so we don't immediately grab the same one again in a rapid retry loop
				gevent.sleep(self.RETRYABLE_UPLOAD_ERROR_WAIT_INTERVAL)
			return

		# Success! Set TRANSCODING or DONE and clear any previous error.
		# Also set thumbnail_last_written if we wrote a thumbnail.
		success_state = 'TRANSCODING' if upload_backend.needs_transcode else 'DONE'
		kwargs = {}
		if success_state == 'DONE':
			kwargs["upload_time"] = datetime.datetime.utcnow()
		if thumbnail is not None:
			kwargs["thumbnail_last_written"] = hashlib.sha256(thumbnail).digest()
		set_row(state=success_state, video_id=video_id, video_link=video_link, error=None, **kwargs)

		self.logger.info("Successfully cut and uploaded job {} as {}".format(format_job(job), video_link))
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

	def __init__(self, location, backend, dbmanager, stop, zulip_client):
		"""
		backend is an upload backend that supports transcoding
		and defines check_status().
		Conn is a database connection.
		Stop is an Event triggering graceful shutdown when set.
		"""
		self.location = location
		self.backend = backend
		self.dbmanager = dbmanager
		self.stop = stop
		self.zulip_client = zulip_client
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
				videos_transcoding.labels(self.location).set(len(ids))
				self.logger.info("Found {} videos in TRANSCODING".format(len(ids)))
				ids = self.check_ids(ids)
				if ids:
					self.logger.info("{} videos are done".format(len(ids)))
					done = self.mark_done(ids)
					for video_id, title in ids.values():
						self.post_to_zulip(video_id, title)
					videos_marked_done.labels(self.location).inc(done)
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
			SELECT id, video_id, video_title
			FROM events
			WHERE state = 'TRANSCODING' AND upload_location = %(location)s
		""", location=self.location)
		return {id: (video_id, title) for id, video_id, title in result.fetchall()}

	def check_ids(self, ids):
		# Future work: Set error in DB if video id is not present,
		# and/or try to get more info from yt about what's wrong.
		done = self.backend.check_status([video_id for video_id, title in ids.values()])
		return {
			id: video_id for id, (video_id, title) in ids.items()
			if video_id in done
		}

	def mark_done(self, ids):
		result = query(self.conn, """
			UPDATE events
			SET state = 'DONE', upload_time = %s
			WHERE id = ANY (%s) AND state = 'TRANSCODING'
		""", datetime.datetime.utcnow(), list(ids.keys()))
		return result.rowcount

	def post_to_zulip(self, video_id, title):
		if self.zulip_client is None:
			return
		text = f"[{title}](https://youtu.be/{video_id})"
		self.zulip_client.send_to_stream("bot-spam", "Uploaded Videos", text)


UPDATE_JOB_PARAMS = [
	"video_id",
	"video_channel",
	"video_quality",
	"video_title",
	"video_description",
	"video_tags",
	"public",
	"thumbnail_mode",
	"thumbnail_time",
	"thumbnail_template",
	"thumbnail_image",
	"thumbnail_crop",
	"thumbnail_location",
	"thumbnail_last_written",
]

class VideoUpdater(object):
	CHECK_INTERVAL = 10 # this is slow to reduce the chance of multiple cutters updating the same row
	ERROR_RETRY_INTERVAL = 20

	def __init__(self, location, segments_path, backend, dbmanager, tags, stop):
		"""
		backend is an upload backend that supports video updates.
		Stop is an Event triggering graceful shutdown when set.
		"""
		self.location = location
		self.segments_path = segments_path
		self.backend = backend
		self.dbmanager = dbmanager
		self.tags = tags
		self.stop = stop
		self.logger = logging.getLogger(type(self).__name__)

	def wait(self, interval):
		"""Wait for INTERVAL with jitter, unless we're stopping"""
		self.stop.wait(common.jitter(interval))

	def run(self):
		self.conn = self.dbmanager.get_conn()
		while not self.stop.is_set():
			try:
				videos = self.get_videos()
				self.logger.info("Found {} videos in MODIFIED".format(len(videos)))
				for job in videos:
					# NOTE: Since we aren't claiming videos, it's technically possible for this
					# to happen:
					# 1. we get MODIFIED video with title A
					# 2. title is updated to B in database
					# 3. someone else updates it to B in backend
					# 4. we update it to A in backend
					# 5. it appears to be successfully updated with B, but the title is actually A.
					# This is unlikely and not a disaster, so we'll just live with it.

					updates = {}
					try:
						# Update video metadata
						tags = list(set(self.tags + job.video_tags))
						self.backend.update_video(job.video_id, job.video_title, job.video_description, tags, job.public)

						# Update thumbnail if needed. This might fail if we don't have the right segments,
						# but that should be very rare and can be dealt with out of band.
						if job.thumbnail_mode != 'NONE':
							thumbnail_image = job.thumbnail_image
							if thumbnail_image is None:
								self.logger.info("Regenerating thumbnail for {}".format(job.id))
								hours_path = os.path.join(self.segments_path, job.video_channel, job.video_quality)
								segments = get_best_segments_for_frame(hours_path, job.thumbnail_time)
								frame = extract_frame(segments, job.thumbnail_time)
								frame = b''.join(frame)
								if job.thumbnail_mode == 'BARE':
									thumbnail_image = frame
								elif job.thumbnail_mode == 'TEMPLATE':
									template, crop, location = get_template(self.dbmanager, job.thumbnail_template, job.thumbnail_crop, job.thumbnail_location)
									self.logger.info('Generating thumbnail from the video frame at {} using {} as template'.format(job.thumbnail_time, job.thumbnail_template))
									thumbnail_image = compose_thumbnail_template(template, frame, crop, location)
								else:
									assert False, "Bad thumbnail mode: {}".format(job.thumbnail_mode)
								updates['thumbnail_image'] = thumbnail_image
							new_hash = hashlib.sha256(thumbnail_image).digest()
							if job.thumbnail_last_written is None or bytes(job.thumbnail_last_written) != new_hash:
								self.logger.info("Setting thumbnail for {}".format(job.id))
								self.backend.set_thumbnail(job.video_id, thumbnail_image)
								updates['thumbnail_last_written'] = new_hash
							else:
								self.logger.info("No change in thumbnail image for {}".format(job.id))
					except Exception as ex:
						# for HTTPErrors, getting http response body is also useful
						if isinstance(ex, requests.HTTPError):
							self.logger.exception("Failed to update video: {}".format(ex.response.content))
							ex = "{}: {}".format(ex, ex.response.content)
						else:
							self.logger.exception("Failed to update video")

						# Explicitly retryable errors aren't problems
						if isinstance(ex, UploadError) and ex.retryable:
							self.logger.warning("Retryable error when updating video", exc_info=True)
							# By giving up without marking as done or errored, another cutter should get it.
							# Or we'll get it next loop.
						else:
							self.mark_errored(job.id, "Failed to update video: {}".format(ex))

						continue

					marked = self.mark_done(job, updates)
					if marked:
						assert marked == 1
						self.logger.info("Updated video {}".format(job.id))
					else:
						self.logger.warning("Updated video {}, but row has changed since. Did someone else already update it?".format(job.id))
				self.wait(self.CHECK_INTERVAL)
			except Exception:
				self.logger.exception("Error in VideoUpdater")
				# To ensure a fresh slate and clear any DB-related errors, get a new conn on error.
				# This is heavy-handed but simple and effective.
				self.conn = self.dbmanager.get_conn()
				self.wait(self.ERROR_RETRY_INTERVAL)

	def get_videos(self):
		# To avoid exhausting API quota, errors aren't retryable.
		# We ignore any rows where error is not null.
		built_query = sql.SQL("""
			SELECT id, {}
			FROM events
			WHERE state = 'MODIFIED' AND error IS NULL AND upload_location = %(location)s
		""").format(
			sql.SQL(", ").join(sql.Identifier(key) for key in UPDATE_JOB_PARAMS)
		)
		return list(query(self.conn, built_query, location=self.location))

	def mark_done(self, job, updates):
		"""We don't want to set to DONE if the video has been modified *again* since
		we saw it."""
		updates['state'] = 'DONE'
		built_query = sql.SQL("""
			UPDATE events
			SET {}
			WHERE state = 'MODIFIED' AND {}
		""").format(
			sql.SQL(", ").join(
				sql.SQL("{} = {}").format(
					sql.Identifier(key), get_column_placeholder("new_{}".format(key)),
				) for key in updates
			),
			sql.SQL(" AND ").join(
				# NULL != NULL, so we need "IS NOT DISTINCT FROM" to mean "equal, even if they're null"
				sql.SQL("{} IS NOT DISTINCT FROM {}").format(sql.Identifier(key), get_column_placeholder(key))
				for key in UPDATE_JOB_PARAMS
			)
		)
		updates = {"new_{}".format(key): value for key, value in updates.items()}
		return query(self.conn, built_query, **job._asdict(), **updates).rowcount

	def mark_errored(self, id, error):
		# We don't overwrite any existing error, it is most likely from another attempt to update
		# anyway.
		query(self.conn, """
			UPDATE events
			SET error = %s
			WHERE id = %s and error IS NULL
		""", error, id)


def main(
	dbconnect,
	config,
	creds_file,
	name=None,
	base_dir=".",
	tags='',
	metrics_port=8003,
	backdoor_port=0,
	uploader_explicit_only=False,
):
	"""dbconnect should be a postgres connection string, which is either a space-separated
	list of key=value pairs, or a URI like:
		postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE

	config should be a json blob mapping upload location names to a config object
	for that location. This config object should contain the keys:
		type:
			the name of the upload backend type
		cut_type:
			One of 'fast' or 'full'. Default 'full'. This indicates whether to use
			fast_cut_segments() or full_cut_segments() for this location.
	along with any additional config options defined for that backend type.

	creds_file should contain any required credentials for the upload backends, as JSON.

	name defaults to hostname.

	tags should be a comma-seperated list of tags to attach to all videos.
	"""
	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	if name is None:
		name = socket.gethostname()

	tags = tags.split(',') if tags else []

	stop = gevent.event.Event()
	gevent.signal_handler(signal.SIGTERM, stop.set) # shut down on sigterm

	logging.info("Starting up")

	# We have two independent jobs to do - to perform cut jobs (cutter),
	# and to check the status of transcoding videos to see if they're done (transcode checker).
	# We want to error if either errors, and shut down if either exits.
	dbmanager = None
	stopping = gevent.event.Event()
	dbmanager = DBManager(dsn=dbconnect)
	while True:
		try:
			# Get a test connection so we know the database is up,
			# this produces a clearer error in cases where there's a connection problem.
			conn = dbmanager.get_conn()
		except Exception:
			delay = common.jitter(10)
			logging.warning('Cannot connect to database. Retrying in {:.0f} s'.format(delay), exc_info=True)
			stop.wait(delay)
		else:
			# put it back so it gets reused on next get_conn()
			dbmanager.put_conn(conn)
			break

	with open(creds_file) as f:
		credentials = json.load(f)

	config = json.loads(config)
	upload_locations = {}
	needs_transcode_check = {}
	needs_updater = {}
	for location, backend_config in config.items():
		backend_type = backend_config.pop('type')
		no_updater = backend_config.pop('no_updater', False)
		no_uploader = backend_config.pop('no_uploader', False)
		cut_type = backend_config.pop('cut_type', 'full')
		zulip_creds = backend_config.pop('zulip_creds', None)
		if backend_type == 'youtube':
			backend_type = Youtube
		elif backend_type == 'local':
			backend_type = Local
		elif backend_type == 'local-archive':
			backend_type = LocalArchive
		else:
			raise ValueError("Unknown upload backend type: {!r}".format(backend_type))
		backend = backend_type(credentials, **backend_config)
		if cut_type in ('fast', 'smart'):
			# mark for the given cut type by replacing encoding settings
			backend.encoding_settings = cut_type
		elif cut_type != 'full':
			raise ValueError("Unknown cut type: {!r}".format(cut_type))
		if not no_uploader:
			upload_locations[location] = backend
		if backend.needs_transcode:
			zulip_client = zulip.Client(**zulip_creds) if zulip_creds else None
			needs_transcode_check[location] = backend, zulip_client
		if not no_updater:
			needs_updater[location] = backend

	cutter = Cutter(upload_locations, dbmanager, stop, name, base_dir, tags, uploader_explicit_only)
	transcode_checkers = [
		TranscodeChecker(location, backend, dbmanager, stop, zulip_client)
		for location, (backend, zulip_client) in needs_transcode_check.items()
	]
	updaters = [
		VideoUpdater(location, base_dir, backend, dbmanager, tags, stop)
		for location, backend in needs_updater.items()
	]
	jobs = [gevent.spawn(cutter.run)] + [
		gevent.spawn(transcode_checker.run)
		for transcode_checker in transcode_checkers
	] + [
		gevent.spawn(updater.run)
		for updater in updaters
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
