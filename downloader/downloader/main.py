
import datetime
import errno
import hashlib
import logging
import os
import signal
import uuid
from base64 import b64encode
from contextlib import contextmanager

import argh
import gevent
import gevent.backdoor
import gevent.event
import prometheus_client as prom
import requests
from monotonic import monotonic

import common
import common.dateutil
import common.requests

from .twitch import URLProvider, TwitchProvider, YoutubeProvider


segments_downloaded = prom.Counter(
	"segments_downloaded",
	"Number of segments either partially or fully downloaded",
	["type", "channel", "quality"],
)

segment_duration_downloaded = prom.Counter(
	"segment_duration_downloaded",
	"Total duration of all segments partially or fully downloaded. "
	"Note partial segments still count the full duration.",
	["type", "channel", "quality"],
)

latest_segment = prom.Gauge(
	"latest_segment",
	"Timestamp of the time of the newest segment fully downloaded",
	["channel", "quality"],
)

ad_segments_ignored = prom.Counter(
	"ad_segments_ignored",
	"Number of ad segments we saw and avoided downloading",
	["channel", "quality"],
)


class TimedOutError(Exception):
	pass


@contextmanager
def soft_hard_timeout(logger, description, timeouts, on_soft_timeout):
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
	soft_timeout, hard_timeout = timeouts
	# Finished is set after we're done to flag to the pending soft timeout callback
	# that it shouldn't run.
	finished = False
	def dispatch_soft_timeout():
		if finished:
			# We finished before soft timeout was hit
			return
		logger.warning("Hit soft timeout {}s while {}".format(soft_timeout, description))
		on_soft_timeout()
	gevent.spawn_later(soft_timeout, dispatch_soft_timeout)
	error = TimedOutError("Timed out after {}s while {}".format(hard_timeout, description))
	try:
		with gevent.Timeout(hard_timeout, error):
			yield
	finally:
		finished = True


class StreamsManager(object):
	"""Keeps track of what qualities are being downloaded and the workers doing so.
	Re-fetches master playlist when needed and starts new stream workers.
	This is all to ensure that broken or bad media playlist urls are refreshed
	in a timely manner.

	The stream_workers map lists workers for each quality. Generally there should only be
	one, but during switchover there may be 2 - one old one continuing to (try to) operate while
	the second one confirms it's working. While trying to get a url working, it won't retry, it'll
	just ask the manager immediately to create yet another new worker then quit.
	When one successfully fetches a playlist for the first time, and confirms it has a non-ad
	segment, it marks all older workers as able to shut down by calling manager.mark_working().
	We wait for a non-ad segment because on first connect, a preroll ad may play.
	We don't want to give up on the old connection (which may contain segments covering
	the time the preroll ad is playing) until the ad is over.

	Creation of a new stream worker may be triggered by:
	* An existing worker failing to refresh its playlist
	* The master playlist finding a quality url it doesn't have already
	* A worker is older than MAX_WORKER_AGE

	The master playlist is only re-fetched as needed. Reasons to re-fetch:
	* No url is known for at least one quality
	* Someone has requested it (eg. because the previous attempt failed, or a worker needs a new url)
	* A worker is older than MAX_WORKER_AGE
	"""

	# Important streams are retried more aggressively when down
	IMPORTANT_FETCH_MIN_INTERVAL = 5
	FETCH_MIN_INTERVAL = 20

	FETCH_TIMEOUTS = 5, 30

	def __init__(self, provider, channel, base_dir, qualities, important=False):
		self.provider = provider
		self.channel = channel
		self.logger = logging.getLogger("StreamsManager({})".format(channel))
		self.base_dir = base_dir
		self.stream_workers = {name: [] for name in qualities} # {quality name: [workers]}
		self.latest_urls = {} # {quality name: (fetch time, url)}
		self.latest_urls_changed = gevent.event.Event() # set when latest_urls changes
		self.refresh_needed = gevent.event.Event() # set to tell main loop to refresh now
		self.stopping = gevent.event.Event() # set to tell main loop to stop
		self.important = important
		self.master_playlist_log_level = logging.INFO if important else logging.DEBUG
		if self.important:
			self.FETCH_MIN_INTERVAL = self.IMPORTANT_FETCH_MIN_INTERVAL

	def mark_working(self, worker):
		"""Notify the manager that the given worker is up and running,
		and any older workers are safe to stop."""
		workers = self.stream_workers[worker.quality]
		if worker not in workers:
			self.logger.warning("Worker {} called mark_working() but wasn't in known list: {}".format(worker, workers))
			return
		# stop everything older than given worker
		for old in workers[:workers.index(worker)]:
			old.stop()

	def trigger_new_worker(self, worker):
		"""Called when a worker decides a new worker for a quality is needed, eg. if it seems to be
		failing. Causes a new worker with a fresh url to be created.
		If worker's url is the same as the latest url, blocks until a new url has been fetched.
		This only has effect if the worker is the current latest worker.
		"""
		workers = self.stream_workers[worker.quality]
		if worker not in workers:
			self.logger.warning("Worker {} called trigger_new_worker() but wasn't in known list: {}".format(worker, workers))
			return
		if worker is not workers[-1]:
			self.logger.info("Ignoring request to start new worker for {} as old one is not latest".format(worker.quality))
			return
		self.logger.info("Starting new worker for {} by request of old worker".format(worker.quality))
		self.wait_for_new_url(worker.quality, worker.url)
		self.start_worker(worker.quality)
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

	def wait_for_new_url(self, quality, old_url):
		"""Trigger urls to be re-fetched, and block until a different one is received."""
		while True:
			new_time, new_url = self.latest_urls[quality]
			if new_url != old_url:
				return
			self.logger.info("Triggering master playlist refresh as we need a new url")
			self.trigger_refresh()
			self.latest_urls_changed.wait()

	def stop(self):
		"""Shut down all workers and stop capturing stream."""
		self.logger.info("Stopping")
		self.stopping.set()

	def start_worker(self, quality):
		"""Start a new worker for given quality"""
		# it's possible for fetch_latest to call us after we've started stopping,
		# in that case do nothing.
		if self.stopping.is_set():
			self.logger.info("Ignoring worker start as we are stopping")
			return
		url_time, url = self.latest_urls[quality]
		worker = StreamWorker(self, quality, url, url_time)
		self.stream_workers[quality].append(worker)
		gevent.spawn(worker.run)

	def fetch_latest(self):
		"""Re-fetch master playlist and start new workers if needed"""
		try:
			# Fetch playlist. On soft timeout, retry.
			self.logger.log(self.master_playlist_log_level, "Fetching master playlist")
			fetch_time = monotonic()
			with soft_hard_timeout(self.logger, "fetching master playlist", self.FETCH_TIMEOUTS, self.trigger_refresh):
				new_urls = self.provider.get_media_playlist_uris(list(self.stream_workers.keys()))
			self.update_urls(fetch_time, new_urls)
			for quality, workers in self.stream_workers.items():
				# warn and retry if the url is missing
				if quality not in new_urls:
					self.logger.warning("Stream {} could not be found in latest master playlist, re-queueing refresh".format(quality))
					self.trigger_refresh()
					continue
				# is it newly found?
				if not workers and quality in self.latest_urls:
					self.logger.info("Starting new worker for {} as none exist".format(quality))
					self.start_worker(quality)
					continue
				latest_worker = workers[-1]
				# is the old worker too old?
				if latest_worker.age() > self.provider.MAX_WORKER_AGE:
					self.logger.info("Starting new worker for {} as the latest is too old ({}h)".format(quality, latest_worker.age() / 3600.))
					self.start_worker(quality)
		except Exception as e:
			if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 404:
				# Log about important streams being down at info, but others at debug.
				self.logger.log(self.master_playlist_log_level, "Stream is not up. Retrying.")
				self.trigger_refresh()
			else:
				self.logger.exception("Failed to fetch master playlist")
				# don't retry on hard timeout as we already retried on soft timeout
				if not isinstance(e, TimedOutError):
					self.trigger_refresh()

	def run(self):
		self.trigger_refresh() # on first round, always go immediately
		while not self.stopping.is_set():
			# clamp time to max age to non-negative, and default to 0 if no workers exist
			time_to_next_max_age = max(0, min([
				self.provider.MAX_WORKER_AGE - workers[-1].age()
				for workers in self.stream_workers.values() if workers
			] or [0]))
			self.logger.log(self.master_playlist_log_level, "Next master playlist refresh in at most {} sec".format(time_to_next_max_age))
			# wait until refresh triggered, next max age reached, or we're stopping (whichever happens first)
			gevent.wait([self.stopping, self.refresh_needed], timeout=time_to_next_max_age, count=1)
			if not self.stopping.is_set():
				self.refresh_needed.clear()
				gevent.spawn(self.fetch_latest)
			# wait min retry interval with jitter, unless we're stopping
			self.stopping.wait(common.jitter(self.FETCH_MIN_INTERVAL))
		self.logger.info("Stopping workers")
		stream_workers = list(self.stream_workers.values())
		for workers in stream_workers:
			for worker in workers:
				worker.stop()
		for workers in stream_workers:
			for worker in workers:
				worker.done.wait()


class StreamWorker(object):
	"""Handles downloading segments for a particular media playlist.

	If it fails to fetch its playlist (or hits the soft timeout), it tells the manager
	to start a new worker with a new url.

	If the url had been working (ie. that wasn't the first fetch), it will also stay alive and
	attempt to use the old url until a new worker tells it to stand down,
	or a 403 or 404 is received (as this indicates the url is expired).

	Since segment urls returned for a particular media playlist url are stable, we have an easier
	time of managing downloading those:
	* Every time a new URL is seen, a new SegmentGetter is created
	* SegmentGetters will retry the same URL until they succeed, or get a 403 or 404 indicating
	  the url has expired.
	"""

	FETCH_TIMEOUTS = 5, 90
	FETCH_RETRY_INTERVAL = 1
	FETCH_POLL_INTERVAL = 2

	def __init__(self, manager, quality, url, url_time):
		self.manager = manager
		self.logger = manager.logger.getChild("StreamWorker({})@{:x}".format(quality, id(self)))
		self.quality = quality
		self.url = url
		self.url_time = url_time
		self.stopping = gevent.event.Event() # set to stop main loop
		self.getters = {} # map from url to SegmentGetter
		self.done = gevent.event.Event() # set when stopped and all getters are done
		# Set up a Session for connection pooling. Note that if we have an issue,
		# a new worker is created and so it gets a new session, just in case there's a problem
		# with our connection pool.
		# This worker's SegmentGetters will use its session by default for performance,
		# but will fall back to a new one if something goes wrong.
		self.session = common.requests.InstrumentedSession()

	def __repr__(self):
		return "<{} at 0x{:x} for stream {!r}>".format(type(self).__name__, id(self), self.quality)
	__str__ = __repr__

	def age(self):
		"""Return age of our url"""
		return monotonic() - self.url_time

	def stop(self):
		"""Tell the worker to shut down"""
		self.stopping.set()

	def run(self):
		self.logger.info("Worker starting")
		try:
			self._run()
		except Exception:
			self.logger.exception("Worker failed")
			self.trigger_new_worker()
		else:
			self.logger.info("Worker stopped")
		finally:
			for getter in list(self.getters.values()):
				getter.done.wait()
			self.done.set()
			self.manager.stream_workers[self.quality].remove(self)

	def trigger_new_worker(self):
		self.manager.trigger_new_worker(self)

	def wait(self, interval):
		"""Wait for given interval with jitter, unless we're stopping"""
		self.stopping.wait(common.jitter(interval))

	def _run(self):
		first = True
		while not self.stopping.is_set():

			self.logger.debug("Getting media playlist {}".format(self.url))
			try:
				with soft_hard_timeout(self.logger, "getting media playlist", self.FETCH_TIMEOUTS, self.trigger_new_worker):
					playlist = self.manager.provider.get_media_playlist(self.url, session=self.session)
			except Exception as e:
				self.logger.warning("Failed to fetch media playlist {}".format(self.url), exc_info=True)
				self.trigger_new_worker()
				if first:
					self.logger.warning("Failed on first fetch, stopping")
					self.stop()
				elif isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code in (403, 404):
					self.logger.warning("Failed with {}, stopping".format(e.response.status_code))
					self.stop()
				self.wait(self.FETCH_RETRY_INTERVAL)
				continue

			# We successfully got the playlist at least once
			first = False

			# Start any new segment getters
			date = None # tracks date in case some segment doesn't include it
			for segment in playlist.segments:
				if segment.ad_reason:
					self.logger.info("Ignoring ad segment: {}".format(segment.ad_reason))
					ad_segments_ignored.labels(self.manager.channel, self.quality).inc()
					continue

				# We've got our first non-ad segment, so we're good to take it from here.
				self.manager.mark_working(self)

				if segment.date:
					date = common.dateutil.parse(segment.date)
				if segment.uri not in self.getters:
					if date is None:
						raise ValueError("Cannot determine date of segment")
					self.getters[segment.uri] = SegmentGetter(
						self.logger,
						self.session,
						self.manager.base_dir,
						self.manager.channel,
						self.quality,
						segment,
						date,
					)
					gevent.spawn(self.getters[segment.uri].run)
				if date is not None:
					date += datetime.timedelta(seconds=segment.duration)

			# Clean up any old segment getters.
			# Note use of list() to make a copy to avoid modification-during-iteration
			for url, getter in list(self.getters.items()):
				# If segment is done and wasn't in latest fetch
				if getter.done.is_set() and not any(
					segment.uri == url for segment in playlist.segments
				):
					del self.getters[url]

			# Stop if end-of-stream
			if playlist.is_endlist:
				self.logger.info("Stopping due to end-of-playlist")
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
	Retries until it succeeds, or gets a 403 or 404 indicating
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
	FETCH_HEADERS_TIMEOUTS = 5, 60
	FETCH_FULL_TIMEOUTS = 15, 240
	# Experimentally, we've observed that after 60s, stuck requests will be terminated
	# by twitch with incomplete but valid data, without anything indicating an error.
	# We assume anything longer than 60s is "suspect", not to be used if we have a
	# version that was fetched in a more timely manner.
	FETCH_SUSPECT_TIME = 59
	# Overall timeout on the Getter before giving up, to prevent always-failing Getters
	# from growing without bound and causing resource exhaustion issues.
	# The longest we've observed in the wild before a segment goes un-fetchable is 7min
	# or so, to be paranoid we set it to considerably longer than that.
	GIVE_UP_TIMEOUT = 20 * 60

	def __init__(self, parent_logger, session, base_dir, channel, quality, segment, date):
		self.logger = parent_logger.getChild("SegmentGetter@{:x}".format(id(self)))
		self.base_dir = base_dir
		self.channel = channel
		self.quality = quality
		self.segment = segment
		self.date = date
		self.prefix = self.make_path_prefix()
		self.retry = None # Event, set to begin retrying
		self.done = gevent.event.Event() # set when file exists or we give up
		# Our parent's connection pool, but we'll replace it if there's any issues
		self.session = session

	def run(self):
		try:
			while True:
				try:
					self._run()
				except Exception:
					self.logger.exception("Unexpected exception while getting segment {}, retrying".format(self.segment))
					gevent.sleep(common.jitter(self.UNEXPECTED_FAILURE_RETRY))
				else:
					break
		finally:
			self.done.set()

	def _run(self):
		start = monotonic()
		self.logger.debug("Getter started at {}".format(start))
		while not self.exists():
			self.retry = gevent.event.Event()
			worker = gevent.spawn(self.get_segment)
			# wait until worker succeeds/fails or retry is set
			gevent.wait([worker, self.retry], count=1)
			# If worker has returned, and return value is true, we're done
			if worker.ready() and worker.value:
				break
			# If a large amount of time has elapsed since starting, our URL is stale
			# anyway so we might as well give up to avoid cpu and disk usage.
			elapsed = monotonic() - start
			if elapsed > self.GIVE_UP_TIMEOUT:
				self.logger.warning("Getter has been running for {}s, giving up as our URL has expired".format(elapsed))
				break
			# Create a new session, so we don't reuse a connection from the old session
			# which had an error / some other issue. This is mostly just out of paranoia.
			self.session = common.requests.InstrumentedSession()
			# if retry not set, wait for FETCH_RETRY first
			self.retry.wait(common.jitter(self.FETCH_RETRY))
		self.logger.debug("Getter is done")

	def make_path_prefix(self):
		"""Generate leading part of filepath which doesn't change with the hash."""
		return os.path.join(
			self.base_dir,
			self.channel,
			self.quality,
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
			suspect: Segment appears to be complete, but we suspect it is not. Hash is included.
			partial: Segment is incomplete. Hash is included.
			temp: Segment has not been downloaded yet. A random uuid is added.
		"""
		arg = str(uuid.uuid4()) if type == "temp" else b64encode(hash.digest(), b"-_").decode().rstrip("=")
		return "{}-{}-{}.ts".format(self.prefix, type, arg)

	def exists(self):
		"""Look for an existing, full (non-partial, non-suspect) copy of this segment. Return bool."""
		dirname = os.path.dirname(self.prefix)
		try:
			candidates = os.listdir(dirname)
		except OSError as e:
			# on ENOENT (doesn't exist), return false
			if e.errno != errno.ENOENT:
				raise
			return False
		full_prefix = "{}-full".format(self.prefix)
		return any(
			candidate.startswith(full_prefix)
				# There's almost no way a matching tombstone could already exist, but just in case
				# we'll make sure it isn't counted.
				and not candidate.endswith(".tombstone")
			for candidate in candidates
		)

	def get_segment(self):
		try:
			self._get_segment()
		except Exception:
			self.logger.exception("Failed to get segment {}".format(self.segment))
			return False
		else:
			return True

	def _get_segment(self):
		# save current value of self.retry so we can't set any later instance
		# after a retry for this round has already occurred.
		retry = self.retry
		temp_path = self.make_path("temp")
		hash = hashlib.sha256()
		file_created = False
		try:
			self.logger.debug("Downloading segment {} to {}".format(self.segment, temp_path))
			start_time = monotonic()
			with soft_hard_timeout(self.logger, "getting and writing segment", self.FETCH_FULL_TIMEOUTS, retry.set):
				with soft_hard_timeout(self.logger, "getting segment headers", self.FETCH_HEADERS_TIMEOUTS, retry.set):
					resp = self.session.get(self.segment.uri, stream=True, metric_name='get_segment')
				# twitch returns 403 for expired segment urls, and 404 for very old urls where the original segment is gone.
				# the latter can happen if we have a network issue that cuts us off from twitch for some time.
				if resp.status_code in (403, 404):
					self.logger.warning("Got {} for segment, giving up: {}".format(resp.status_code, self.segment))
					return
				resp.raise_for_status()
				common.ensure_directory(temp_path)
				with open(temp_path, 'wb') as f:
					file_created = True
					# We read chunk-wise in 8KiB chunks. Note that if the connection cuts halfway,
					# we may lose part of the last chunk even though we did receive it.
					# This is a small enough amount of data that we don't really care.
					for chunk in resp.iter_content(8192):
						common.writeall(f.write, chunk)
						hash.update(chunk)
		except Exception as e:
			if file_created:
				partial_path = self.make_path("partial", hash)
				self.logger.warning("Saving partial segment {} as {}".format(temp_path, partial_path))
				common.rename(temp_path, partial_path)
				segments_downloaded.labels(type="partial", channel=self.channel, quality=self.quality).inc()
				segment_duration_downloaded.labels(type="partial", channel=self.channel, quality=self.quality).inc(self.segment.duration)
			raise e
		else:
			request_duration = monotonic() - start_time
			segment_type = "full" if request_duration < self.FETCH_SUSPECT_TIME else "suspect"
			full_path = self.make_path(segment_type, hash)
			self.logger.debug("Saving completed segment {} as {}".format(temp_path, full_path))
			common.rename(temp_path, full_path)
			segments_downloaded.labels(type=segment_type, channel=self.channel, quality=self.quality).inc()
			segment_duration_downloaded.labels(type=segment_type, channel=self.channel, quality=self.quality).inc(self.segment.duration)
			# Prom doesn't provide a way to compare value to gauge's existing value,
			# we need to reach into internals
			stat = latest_segment.labels(channel=self.channel, quality=self.quality)
			timestamp = (self.date - datetime.datetime(1970, 1, 1)).total_seconds()
			stat.set(max(stat._value.get(), timestamp)) # NOTE: not thread-safe but is gevent-safe


def parse_channel(channel):
	if ":" in channel:
		channel, type, url = channel.split(":", 2)
	else:
		type = "twitch"
		url = None
	important = channel.endswith("!")
	channel = channel.rstrip("!")
	return channel, important, type, url


@argh.arg('channels', nargs="+", type=parse_channel, help=
	"Twitch channels to watch. Add a '!' suffix to indicate they're expected to be always up. "
	"This affects retry interval, error reporting and monitoring. "
	"Non-twitch URLs can also be given with the form CHANNEL[!]:TYPE:URL"
)
def main(channels, base_dir=".", qualities="source", metrics_port=8001, backdoor_port=0, twitch_auth_file=None):
	qualities = qualities.split(",") if qualities else []

	twitch_auth_token = None
	if twitch_auth_file is not None:
		with open(twitch_auth_file) as f:
			twitch_auth_token = f.read().strip()

	managers = []
	for channel, important, type, url in channels:
		if type == "twitch":
			provider = TwitchProvider(channel, auth_token=twitch_auth_token)
		else:
			raise ValueError(f"Unknown type {type!r}")
		manager = StreamsManager(provider, channel, base_dir, qualities, important=important)
		managers.append(manager)

	def stop():
		for manager in managers:
			manager.stop()

	gevent.signal_handler(signal.SIGTERM, stop) # shut down on sigterm

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	logging.info("Starting up")

	workers = [gevent.spawn(manager.run) for manager in managers]

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
	# 3. Check if any of them failed. If they did, report it. If mulitple failed, we report
	#    one arbitrarily.
	for worker in workers:
		worker.get() # re-raise error if failed

	logging.info("Gracefully stopped")
