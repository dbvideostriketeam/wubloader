
import datetime
import errno
import hashlib
import logging
import os
import random
import sys
import uuid
from base64 import b64encode
from contextlib import contextmanager

import dateutil.parser
import gevent
import gevent.event
import requests
from monotonic import monotonic

import twitch


class TimedOutError(Exception):
	pass


@contextmanager
def soft_hard_timeout(description, (soft_timeout, hard_timeout), on_soft_timeout):
	"""Context manager that wraps a piece of code in a pair of timeouts,
	a "soft" timeout and a "hard" one. If the block does not complete before
	the soft timeout, the given on_soft_timeout() function is called in a new greenlet.
	If it doesn't complete before the hard timeout, a TimedOutError is raised.

	Description is a short string, used for logging and error messages.

	Note that the timeouts are given as a tuple pair for ease of use,
	as it's generally easier to pass them around as a pair.

	A typical use-case is for the soft timeout to trigger some other code to begin
	retrying, even as the original code continues to hold out in hope the call eventually
	succeeds.
	"""
	# Finished is set after we're done to flag to the pending soft timeout callback
	# that it shouldn't run.
	finished = False
	def dispatch_soft_timeout():
		if finished:
			# We finished before soft timeout was hit
			return
		logging.warning("Hit soft timeout {}s while {}".format(soft_timeout, description))
		on_soft_timeout()
	gevent.spawn_later(soft_timeout, dispatch_soft_timeout)
	error = TimedOutError("Timed out after {}s while {}".format(hard_timeout, description))
	try:
		with gevent.Timeout(hard_timeout, error):
			yield
	finally:
		finished = True


def jitter(interval):
	"""Apply some 'jitter' to an interval. This is a random +/- 10% change in order to
	smooth out patterns and prevent everything from retrying at the same time.
	"""
	return interval * (0.9 + 0.2 * random.random())


class StreamsManager(object):
	"""Keeps track of what streams are being downloaded and the workers doing so.
	Re-fetches master playlist when needed and starts new stream workers.
	This is all to ensure that broken or bad media playlist urls are refreshed
	in a timely manner.

	The stream_workers map lists workers for each stream. Generally there should only be
	one, but during switchover there may be 2 - one old one continuing to (try to) operate while
	the second one confirms it's working. While trying to get a url working, it won't retry, it'll
	just ask the manager immediately to create yet another new worker then quit.
	When one successfully fetches a playlist for the first time, it marks all older
	workers as able to shut down by calling manager.mark_working().

	Creation of a new stream worker may be triggered by:
	* An existing worker failing to refresh its playlist
	* The master playlist finding a stream url it doesn't have already
	* A worker is older than MAX_WORKER_AGE

	The master playlist is only re-fetched as needed. Reasons to re-fetch:
	* No url is known for at least one stream
	* Someone has requested it (eg. because the previous attempt failed, or a worker needs a new url)
	* A worker is older than MAX_WORKER_AGE
	"""

	FETCH_MIN_INTERVAL = 5
	FETCH_TIMEOUTS = 5, 30
	MAX_WORKER_AGE = 20*60*60 # 20 hours, twitch's media playlist links expire after 24 hours

	def __init__(self, channel, base_dir, qualities):
		self.channel = channel
		self.base_dir = base_dir
		self.stream_workers = {name: [] for name in qualities + ["source"]} # {stream name: [workers]}
		self.latest_urls = {} # {stream name: (fetch time, url)}
		self.latest_urls_changed = gevent.event.Event() # set when latest_urls changes
		self.refresh_needed = gevent.event.Event() # set to tell main loop to refresh now
		self.stopping = gevent.event.Event() # set to tell main loop to stop

	def mark_working(self, worker):
		"""Notify the manager that the given worker is up and running,
		and any older workers are safe to stop."""
		workers = self.stream_workers[worker.stream]
		if worker not in workers:
			logging.warning("Worker {} called mark_working() but wasn't in known list: {}".format(worker, workers))
			return
		# stop everything older than given worker
		for old in workers[:workers.index(worker)]:
			old.stop()

	def trigger_new_worker(self, worker):
		"""Called when a worker decides a new worker for a stream is needed, eg. if it seems to be
		failing. Causes a new worker with a fresh url to be created.
		If worker's url is the same as the latest url, blocks until a new url has been fetched.
		This only has effect if the worker is the current latest worker.
		"""
		workers = self.stream_workers[worker.stream]
		if worker not in workers:
			logging.warning("Worker {} called trigger_new_worker() but wasn't in known list: {}".format(worker, workers))
			return
		if worker is not workers[-1]:
			logging.info("Ignoring request to start new worker for {} as old one is not latest".format(worker.stream))
			return
		logging.info("Starting new worker for {} by request of old worker".format(worker.stream))
		self.wait_for_new_url(worker.stream, worker.url)
		self.start_worker(worker.stream)
		self.trigger_refresh()

	def trigger_refresh(self):
		"""Indicate that the master playlist needs to be re-fetched at the next available opportunity."""
		self.refresh_needed.set()

	def update_urls(self, time, new_urls):
		"""Update the urls for streams, and notify anyone waiting"""
		self.latest_urls.update({
			name: (time, url)
			for name, url in new_urls.items()
		})
		# set the old Event, and create a new one for any new waiters
		self.latest_urls_changed.set()
		self.latest_urls_changed = gevent.event.Event()

	def wait_for_new_url(self, stream, old_url):
		"""Trigger urls to be re-fetched, and block until a different one is received."""
		while True:
			new_time, new_url = self.latest_urls[stream]
			if new_url != old_url:
				return
			logging.info("Triggering master playlist refresh as we need a new url")
			self.trigger_refresh()
			self.latest_urls_changed.wait()

	def stop(self):
		"""Shut down all workers and stop capturing stream."""
		logging.info("Stopping streams manager")
		self.stopping.set()

	def start_worker(self, stream):
		"""Start a new worker for given stream"""
		url_time, url = self.latest_urls[stream]
		worker = StreamWorker(self, stream, url, url_time)
		self.stream_workers[stream].append(worker)
		gevent.spawn(worker.run)

	def fetch_latest(self):
		"""Re-fetch master playlist and start new workers if needed"""
		try:
			# Fetch playlist. On soft timeout, retry.
			logging.info("Fetching master playlist")
			fetch_time = monotonic()
			with soft_hard_timeout("fetching master playlist", self.FETCH_TIMEOUTS, self.trigger_refresh):
				master_playlist = twitch.get_master_playlist(self.channel)
			new_urls = twitch.get_media_playlist_uris(master_playlist, self.stream_workers.keys())
			self.update_urls(fetch_time, new_urls)
			for stream, workers in self.stream_workers.items():
				# warn and retry if the url is missing
				if stream not in new_urls:
					logging.warning("Stream {} could not be found in latest master playlist, re-queueing refresh".format(stream))
					self.trigger_refresh()
				# is it newly found?
				if not workers and stream in self.latest_urls:
					logging.info("Starting new worker for {} as none exist".format(stream))
					self.start_worker(stream)
				latest_worker = workers[-1]
				# is the old worker too old?
				if latest_worker.age() > self.MAX_WORKER_AGE:
					logging.info("Starting new worker for {} as the latest is too old ({}h)".format(stream, latest_worker.age() / 3600.))
					self.start_worker(stream)
		except Exception as e:
			if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 404:
				logging.info("Stream is not up. Retrying.")
				self.trigger_refresh()
			else:
				logging.exception("Failed to fetch master playlist")
				# don't retry on hard timeout as we already retried on soft timeout
				if not isinstance(e, TimedOutError):
					self.trigger_refresh()

	def run(self):
		self.trigger_refresh() # on first round, always go immediately
		while not self.stopping.is_set():
			# clamp time to max age to non-negative, and default to 0 if no workers exist
			times_to_max_age = max(0, min([
				self.MAX_WORKER_AGE - workers[-1].age()
				for workers in self.stream_workers.values() if workers
			] + [0])
			# wait until refresh triggered or next max age reached
			logging.info("Next master playlist refresh in at most {} sec".format(time_to_next_max_age))
			self.refresh_needed.wait(time_to_next_max_age)
			self.refresh_needed.clear()
			gevent.spawn(self.fetch_latest)
			# wait min retry interval with jitter, unless we're stopping
			self.stopping.wait(jitter(self.FETCH_MIN_INTERVAL))
		logging.info("Stopping workers")
		for workers in self.stream_workers.values():
			for worker in workers:
				worker.stop()
			for worker in workers:
				worker.done.wait()


class StreamWorker(object):
	"""Handles downloading segments for a particular media playlist.

	If it fails to fetch its playlist (or hits the soft timeout), it tells the manager
	to start a new worker with a new url.

	If the url had been working (ie. that wasn't the first fetch), it will also stay alive and
	attempt to use the old url until a new worker tells it to stand down,
	or a 403 Forbidden is received (as this indicates the url is expired).

	Since segment urls returned for a particular media playlist url are stable, we have an easier
	time of managing downloading those:
	* Every time a new URL is seen, a new SegmentGetter is created
	* SegmentGetters will retry the same URL until they succeed, or get a 403 Forbidden indicating
	  the url has expired.
	"""

	FETCH_TIMEOUTS = 5, 90
	FETCH_RETRY_INTERVAL = 1
	FETCH_POLL_INTERVAL = 2

	def __init__(self, manager, stream, url, url_time):
		self.manager = manager
		self.stream = stream
		self.url = url
		self.url_time = url_time
		self.stopping = gevent.event.Event() # set to stop main loop
		self.getters = {} # map from url to SegmentGetter
		self.done = gevent.event.Event() # set when stopped and all getters are done

	def __repr__(self):
		return "<{} at 0x{:x} for stream {!r}>".format(type(self).__name__, id(self), self.stream)
	__str__ = __repr__

	def age(self):
		"""Return age of our url"""
		return monotonic() - self.url_time

	def stop(self):
		"""Tell the worker to shut down"""
		self.stopping.set()

	def run(self):
		logging.info("Worker {} starting".format(self))
		try:
			self._run()
		except Exception:
			logging.exception("Worker {} failed".format(self))
			self.trigger_new_worker()
		else:
			logging.info("Worker {} stopped".format(self))
		finally:
			for getter in self.getters.values():
				getter.done.wait()
			self.done.set()
			self.manager.stream_workers[self.stream].remove(self)

	def trigger_new_worker(self):
		self.manager.trigger_new_worker(self)

	def wait(self, interval):
		"""Wait for given interval with jitter, unless we're stopping"""
		self.stopping.wait(jitter(interval))

	def _run(self):
		first = True
		while not self.stopping.is_set():

			logging.debug("{} getting media playlist {}".format(self, self.url))
			try:
				with soft_hard_timeout("getting media playlist", self.FETCH_TIMEOUTS, self.trigger_new_worker):
					playlist = twitch.get_media_playlist(self.url)
			except Exception as e:
				logging.warning("{} failed to fetch media playlist {}".format(self, self.url), exc_info=True)
				self.trigger_new_worker()
				if first:
					logging.warning("{} failed on first fetch, stopping".format(self))
					self.stop()
				elif isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 403:
					logging.warning("{} failed with 403 Forbidden, stopping".format(self))
					self.stop()
				self.wait(self.FETCH_RETRY_INTERVAL)
				continue

			# We successfully got the playlist at least once
			first = False

			# Start any new segment getters
			date = None # tracks date in case some segment doesn't include it
			for segment in playlist.segments:
				if segment.date:
					date = dateutil.parser.parse(segment.date)
				if segment.uri not in self.getters:
					if date is None:
						raise ValueError("Cannot determine date of segment")
					self.getters[segment.uri] = SegmentGetter(self.manager.base_dir, self.stream, segment, date)
					gevent.spawn(self.getters[segment.uri].run)
				if date is not None:
					date += datetime.timedelta(seconds=segment.duration)

			# Clean up any old segment getters
			for url, getter in self.getters.items():
				# If segment is done and wasn't in latest fetch
				if getter.done.is_set() and not any(
					segment.uri == url for segment in playlist.segments
				):
					del self.getters[url]

			# Stop if end-of-stream
			if playlist.is_endlist:
				logging.info("{} stopping due to end-of-playlist".format(self))
				# Trigger a new worker for when the stream comes back up.
				# In the short term this will cause some thrashing until the master playlist
				# starts returning 404, but it's the best way to avoid missing anything
				# if the stream is only very briefly down.
				self.trigger_new_worker()
				self.stop()

			# Wait until next poll
			self.wait(self.FETCH_POLL_INTERVAL)


class SegmentGetter(object):
	"""Fetches a segment and writes it to disk.
	Retries until it succeeds, or gets a 403 Forbidden indicating
	the url has expired.

	Due to retries and multiple workers further up the stack, SegmentGetter needs to
	assume there may be multiple getters trying to get the same segment. It handles this
	by writing to a tempfile first, then atomically renaming to the computed filename
	if it doesn't already exist.
	"""
	UNEXPECTED_FAILURE_RETRY = 0.5
	FETCH_RETRY = 2
	# Headers timeout is timeout before getting the start of a response,
	# full timeout is for the entire download and stream to disk.
	FETCH_HEADERS_TIMEOUTS = 5, 30
	FETCH_FULL_TIMEOUTS = 15, 240

	def __init__(self, base_dir, stream, segment, date):
		self.base_dir = base_dir
		self.stream = stream
		self.segment = segment
		self.date = date
		self.prefix = self.make_path_prefix()
		self.retry = None # Event, set to begin retrying
		self.done = gevent.event.Event() # set when file exists or we give up

	def run(self):
		try:
			while True:
				try:
					self._run()
				except Exception:
					logging.exception("Failure in SegmentGetter {}".format(self.segment))
					gevent.sleep(jitter(self.UNEXPECTED_FAILURE_RETRY))
				else:
					break
		finally:
			self.done.set()

	def _run(self):
		while not self.exists():
			self.retry = gevent.event.Event()
			worker = gevent.spawn(self.get_segment)
			# wait until worker succeeds/fails or retry is set
			gevent.wait([worker, self.retry], count=1)
			# If worker has returned, and return value is true, we're done
			if worker.ready() and worker.value:
				break
			# if retry not set, wait for FETCH_RETRY first
			self.retry.wait(jitter(self.FETCH_RETRY))

	def make_path_prefix(self):
		"""Generate leading part of filepath which doesn't change with the hash."""
		return os.path.join(
			self.base_dir,
			self.stream,
			self.date.strftime("%Y-%m-%dT%H"),
			"{date}-{duration}".format(
				date=self.date.strftime("%M:%S.%f"),
				duration=self.segment.duration,
			),
		)

	def make_path(self, type, hash=None):
		"""Generate filepath for the segment.
		Type may be:
			full: Segment is complete. Hash is included.
			partial: Segment is incomplete. Hash is included.
			temp: Segment has not been downloaded yet. A random uuid is added.
		"""
		arg = str(uuid.uuid4()) if type == "temp" else b64encode(hash.digest(), "-_").rstrip("=")
		return "{}-{}-{}.ts".format(self.prefix, type, arg)

	def exists(self):
		"""Look for an existing, full (non-partial) copy of this segment. Return bool."""
		dirname = os.path.dirname(self.prefix)
		try:
			candidates = os.listdir(dirname)
		except OSError as e:
			# on ENOENT (doesn't exist), return []
			if e.errno != errno.ENOENT:
				raise
			return []
		full_prefix = "{}-full".format(self.prefix)
		return any(candidate.startswith(full_prefix) for candidate in candidates)

	def ensure_directory(self, path):
		"""Create directory that contains path, as well as any parent directories,
		if they don't already exist."""
		dir_path = os.path.dirname(path)
		if os.path.exists(dir_path):
			return
		self.ensure_directory(dir_path)
		try:
			os.mkdir(dir_path)
		except OSError as e:
			# Ignore if EEXISTS. This is needed to avoid a race if two getters run at once.
			if e.errno != errno.EEXIST:
				raise

	def get_segment(self):
		# save current value of self.retry so we can't set any later instance
		# after a retry for this round has already occurred.
		try:
			self._get_segment()
		except Exception:
			logging.exception("Failed to get segment {}".format(self.segment))
			return False
		else:
			return True

	def _get_segment(self):
		temp_path = self.make_path("temp")
		hash = hashlib.sha256()
		file_created = False
		try:
			logging.debug("Getting segment {}".format(self.segment))
			with soft_hard_timeout("getting and writing segment", self.FETCH_FULL_TIMEOUTS, self.retry.set):
				with soft_hard_timeout("getting segment headers", self.FETCH_HEADERS_TIMEOUTS, self.retry.set):
					resp = requests.get(self.segment.uri, stream=True)
				if resp.status_code == 403:
					logging.warning("Got 403 Forbidden for segment, giving up: {}".format(self.segment))
					return
				resp.raise_for_status()
				self.ensure_directory(temp_path)
				with open(temp_path, 'w') as f:
					file_created = True
					# We read chunk-wise in 8KiB chunks. Note that if the connection cuts halfway,
					# we may lose part of the last chunk even though we did receive it.
					# This is a small enough amount of data that we don't really care.
					for chunk in resp.iter_content(8192):
						f.write(chunk)
						hash.update(chunk)
		except Exception:
			# save original exception so we can re-raise it later even though we may be handling
			# another exception in the interim
			ex_type, ex, tb = sys.exc_info()
			if file_created:
				self.rename(temp_path, self.make_path("partial", hash))
			raise ex_type, ex, tb
		else:
			self.rename(temp_path, self.make_path("full", hash))

	def rename(self, old, new):
		"""Atomic rename that succeeds if the target already exists, since we're naming everything
		by hash anyway, so if the filepath already exists the file itself is already there.
		In this case, we delete the source file.
		"""
		try:
			os.rename(old, new)
		except OSError as e:
			if e.errno != errno.EEXIST:
				raise
			os.remove(old)


def main(channel, base_dir=".", qualities=""):
	qualities = qualities.split(",") if qualities else []
	manager = StreamsManager(channel, base_dir, qualities)
	logging.info("Starting up")
	manager.run()
