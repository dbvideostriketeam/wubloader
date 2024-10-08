
import base64
import hashlib
import json
import logging
import os
import random
import re
import string
import signal
import socket
import time
from calendar import timegm
from collections import defaultdict
from datetime import datetime
from itertools import count

import gevent.event
import gevent.queue

from common import atomic_write, listdir
from common.chat import BATCH_INTERVAL, format_batch, get_batch_files, merge_messages
from common.media import download_media, FailedResponse, WrongContent, Rejected

from girc import Client
from monotonic import monotonic
import prometheus_client as prom
import requests

from .keyed_group import KeyedGroup


# These are known to arrive up to MAX_DELAY after their actual time
DELAYED_COMMANDS = [
	"JOIN",
	"PART",
]
# This isn't documented, but we've observed up to 30sec of delay, so we pad a little extra
# and hope it's good enough.
MAX_DELAY = 45

COMMANDS = DELAYED_COMMANDS + [
	"PRIVMSG",
	"CLEARCHAT",
	"CLEARMSG",
	"HOSTTARGET",
	"NOTICE",
	"ROOMSTATE",
	"USERNOTICE",
	"USERSTATE",
]

# Assume we're never more than this amount of time behind the server time
# Worst case if too low: multiple output files for same batch that need merging later.
# Should be greater than MAX_DELAY.
MAX_SERVER_LAG = 60

# When guessing when a non-timestamped event occurred, pad the possible range
# by up to this amount before and after our best guess
ESTIMATED_TIME_PADDING = 5

messages_received = prom.Counter(
	"messages_received",
	"Number of chat messages recieved by the client. 'client' tag is per client instance.",
	["channel", "client", "command"],
)

messages_ignored = prom.Counter(
	"messages_ignored",
	"Number of chat messages that were recieved but ignored for some reason (see reason label)",
	["client", "command", "reason"],
)

messages_written = prom.Counter(
	"messages_written",
	"Number of chat messages recieved and then written out to disk in a batch.",
	["channel", "client", "command"],
)

batch_messages = prom.Histogram(
	"batch_messages",
	"Number of messages in batches written to disk",
	["channel", "client"],
	buckets=[0, 1, 4, 16, 64, 256, 1024],
)

# based on DB2021, an average PRIVMSG is about 600 bytes.
# so since batch_messages goes up to 1024, batch_bytes should go up to ~ 600KB.
# let's just call it 1MB.
batch_bytes = prom.Histogram(
	"batch_bytes",
	"Size in bytes of batches written to disk",
	["channel", "client"],
	buckets=[0, 256, 1024, 4096, 16384, 65536, 262144, 1048576]
)

open_batches = prom.Gauge(
	"open_batches",
	"Number of batches that have at least one pending message not yet written to disk",
	["channel", "client"],
)

server_lag = prom.Gauge(
	"server_lag",
	"Estimated time difference between server-side timestamps and local time, based on latest message",
	["channel", "client"],
)

merge_pass_duration = prom.Histogram(
	"merge_pass_duration",
	"How long it took to run through all batches and merge any duplicates",
)
merge_pass_merges = prom.Histogram(
	"merge_pass_merges",
	"How many merges (times for which more than one batch existed) were done in a single merge pass",
	buckets=[0, 1, 10, 100, 1000, 10000],
)

class Archiver(object):
	def __init__(self, name, base_dir, channels, nick, oauth_token, download_media):
		self.logger = logging.getLogger(type(self).__name__).getChild(name)
		self.name = name
		self.messages = gevent.queue.Queue()
		self.channels = channels
		self.base_dir = base_dir
		self.download_media = download_media
		
		self.stopping = gevent.event.Event()
		self.got_reconnect = gevent.event.Event()
		self.client = Client(
			hostname='irc.chat.twitch.tv',
			port=6697,
			ssl=True,
			nick=nick,
			password=oauth_token,
			twitch=True,
			stop_handler=lambda c: self.stopping.set(),
		)
		for channel in self.channels:
			self.client.channel('#{}'.format(channel)).join()

	def channel_path(self, channel):
		return os.path.join(self.base_dir, channel, "chat")

	def write_batch(self, channel, batch_time, messages):
		# wrapper around general write_batch() function
		write_batch(
			self.channel_path(channel), batch_time, messages,
			size_histogram=batch_bytes.labels(channel=channel, client=self.name),
		)
		batch_messages.labels(channel=channel, client=self.name).observe(len(messages))
		# incrementing a prom counter can be stupidly expensive, collect up per-command values
		# so we can do them in one go
		by_command = defaultdict(lambda: 0)
		for message in messages:
			by_command[message["command"]] += 1
		for command, count in by_command.items():
			messages_written.labels(channel=channel, client=self.name, command=command).inc(count)

	def run(self):
		@self.client.handler(sync=True)
		def handle_message(client, message):
			self.messages.put(message)

		# Twitch sends a RECONNECT shortly before terminating the connection from the server side.
		# This gives us time to start up a new instance of the archiver while keeping this one
		# running, so that we can be sure we don't miss anything. This will cause duplicate batches,
		# but those will get merged later.
		@self.client.handler(command='RECONNECT')
		def handle_reconnect(client, message):
			self.got_reconnect.set()

		self.client.start()

		last_server_time = None
		last_timestamped_message = None
		# {(channel, batch time): [messages]}
		batches = {}
		for channel in self.channels:
			open_batches.labels(channel=channel, client=self.name).set_function(
				lambda: len([1 for c, t in batches if c == channel])
			)

		# Tracks if we've seen the initial ROOMSTATE for each channel we've joined.
		# Everything up to and including this message is per-connection:
		# - a JOIN for us joining the room (even if we were already there on another connection)
		# - a USERSTATE for our user
		# - a ROOMSTATE for the room
		# We ignore all messages before the initial ROOMSTATE.
		initialized_channels = set()

		while not (self.stopping.is_set() and self.messages.empty()):
			# wait until we either have a message, are stopping, or a batch can be closed
			if batches:
				oldest_batch_time = min(batch_time for channel, batch_time in batches.keys())
				next_batch_close = oldest_batch_time + BATCH_INTERVAL + MAX_SERVER_LAG
				self.logger.debug("Next batch close at {} (batch times: {})".format(next_batch_close, list(batches.keys())))
				timeout = max(0, next_batch_close - time.time())
			else:
				timeout = None
			self.logger.debug("Waiting up to {} for message or stop".format(timeout))
			gevent.wait([gevent.spawn(self.messages.peek), self.stopping], count=1, timeout=timeout)

			# close any closable batches
			now = time.time()
			for (channel, batch_time), messages in list(batches.items()):
				if now >= batch_time + BATCH_INTERVAL + MAX_SERVER_LAG:
					del batches[channel, batch_time]
					self.write_batch(channel, batch_time, messages)

			# consume a message if any
			try:
				message = self.messages.get(block=False)
			except gevent.queue.Empty:
				continue

			self.logger.debug("Got message: {}".format(message))

			if message.command not in COMMANDS:
				self.logger.info("Skipping non-whitelisted command: {}".format(message.command))
				messages_ignored.labels(client=self.name, command=message.command, reason="non-whitelisted").inc()
				continue

			# For all message types we capture, the channel name is always the first param.
			if not message.params:
				self.logger.error(f"Skipping malformed message with no params - cannot determine channel: {message}")
				messages_ignored.labels(client=self.name, command=message.command, reason="no-channel").inc()
				continue

			channel = message.params[0].lstrip("#")

			if channel not in self.channels:
				self.logger.error(f"Skipping unexpected message for unrequested channel {channel}")
				messages_ignored.labels(client=self.name, command=message.command, reason="bad-channel").inc()
				continue

			if channel not in initialized_channels:
				self.logger.debug(f"Skipping {message.command} message on non-initialized channel {channel}")
				if message.command == "ROOMSTATE":
					initialized_channels.add(channel)
					self.logger.info(f"Channel {channel} is ready")
				messages_ignored.labels(client=self.name, command=message.command, reason="non-initialized-channel").inc()
				continue

			data = {
				attr: getattr(message, attr)
				for attr in ('command', 'params', 'sender', 'user', 'host', 'tags')
			}
			data['receivers'] = {self.name: message.received_at}
			self.logger.debug("Got message data: {}".format(data))
			messages_received.labels(channel=channel, client=self.name, command=message.command).inc()

			if data['tags'] and data['tags'].get('emotes', '') != '':
				emote_specs = data['tags']['emotes'].split('/')
				emote_ids = [emote_spec.split(':')[0] for emote_spec in emote_specs]
				ensure_emotes(self.base_dir, emote_ids)

			if self.download_media and data['command'] == "PRIVMSG" and len(data["params"]) == 2:
				ensure_image_links(self.base_dir, data["params"][1])

			if data['tags'] and 'tmi-sent-ts' in data['tags']:
				# explicit server time is available
				timestamp = int(data['tags']['tmi-sent-ts']) / 1000. # original is int ms
				last_timestamped_message = message
				last_server_time = timestamp
				server_lag.labels(channel=channel, client=self.name).set(time.time() - timestamp)
				time_range = 0
				self.logger.debug("Message has exact timestamp: {}".format(timestamp))
				# check for any non-timestamped messages which we now know must have been
				# before this message. We need to check this batch and the previous.
				batch_time = int(timestamp / BATCH_INTERVAL) * BATCH_INTERVAL
				for batch in (batch_time, batch_time - BATCH_INTERVAL):
					for msg in batches.get((channel, batch), []):
						time_between = timestamp - msg['time']
						if 0 < time_between < msg['time_range']:
							self.logger.debug("Updating previous message {m[command]}@{m[time]} range {m[time_range]} -> {new}".format(
								m=msg, new=time_between,
							))
							msg['time_range'] = time_between
			elif last_server_time is not None:
				# estimate current server time based on time since last timestamped message
				est_server_time = last_server_time + time.time() - last_timestamped_message.received_at
				# pad either side of the estimated server time, use this as a baseline
				timestamp = est_server_time - ESTIMATED_TIME_PADDING
				time_range = 2 * ESTIMATED_TIME_PADDING
				# if previously timestamped message falls within this range, we know this message
				# came after it
				timestamp = max(timestamp, last_server_time)
			else:
				# we have no idea what the server time is, so we guess as 2x the normal padding
				# starting from local time.
				timestamp = time.time() - 2 * ESTIMATED_TIME_PADDING
				time_range = 3 * ESTIMATED_TIME_PADDING

			if data['command'] in DELAYED_COMMANDS:
				# might have happened MAX_DELAY sooner than otherwise indicated.
				timestamp -= MAX_DELAY
				time_range += MAX_DELAY

			self.logger.debug("Message time determined as {} + up to {}".format(timestamp, time_range))
			data['time'] = timestamp
			data['time_range'] = time_range
			batch_time = int(timestamp / BATCH_INTERVAL) * BATCH_INTERVAL
			batches.setdefault((channel, batch_time), []).append(data)

		# Close any remaining batches
		for (channel, batch_time), messages in batches.items():
			self.write_batch(channel, batch_time, messages)

		self.client.wait_for_stop() # re-raise any errors
		self.logger.info("Client stopped")

	def stop(self):
		self.client.stop()


_EMOTES_RUNNING = KeyedGroup()
def ensure_emotes(base_dir, emote_ids):
	"""Tries to download given emote from twitch if it doesn't already exist.
	This happens in the background and errors are ignored.
	"""
	def _ensure_emote(emote_id, theme, scale):
		url = "https://static-cdn.jtvnw.net/emoticons/v2/{}/default/{}/{}".format(emote_id, theme, scale)
		path = os.path.join(base_dir, "emotes", emote_id, "{}-{}".format(theme, scale))
		if os.path.exists(path):
			logging.debug("Emote {} already exists".format(path))
			return
		logging.info("Fetching emote from {}".format(url))
		try:
			response = requests.get(url)
		except Exception:
			logging.warning("Exception while fetching emote from {}".format(url), exc_info=True)
			return
		if not response.ok:
			logging.warning("Error {} while fetching emote from {}: {}".format(response.status_code, url, response.text))
			return
		atomic_write(path, response.content)
		logging.info("Saved emote {}".format(path))

	for emote_id in emote_ids:
		for theme in ('light', 'dark'):
			for scale in ('1.0', '2.0', '3.0'):
				# to prevent downloading the same emote twice because the first download isn't finished yet,
				# use a KeyedGroup.
				key = base_dir, emote_id, theme, scale
				_EMOTES_RUNNING.spawn(key, _ensure_emote, emote_id, theme, scale)


def wait_for_ensure_emotes():
	_EMOTES_RUNNING.wait()


URL_REGEX = re.compile(r"""
	# Previous char is not a letter. This prevents eg. "foohttp://example.com"
	# Also disallows / as the previous character, otherwise "file:///foo.bar/baz"
	# can match on the "foo.bar/baz" part.
	(?<! [\w/] )
	# optional scheme, which must be http or https (we don't want other schemes)
	(?P<scheme> https?:// )?
	# Hostname, which must contain a dot. Single-part hostnames like "localhost" are valid
	# but we don't want to match them, and this avoids cases like "yes/no" matching.
	# We enforce that the TLD is not fully numeric. No TLDs currently look like this
	# (though it does end up forbidding raw IPv4 addresses), and a common false-positive
	# is "1.5/10" or similar.
	( [a-z0-9-]+ \. )+ [a-z][a-z0-9-]+
	# Optional port
	( : [0-9]+ )?
	# Optional path. We assume a path character can be anything that's not completely disallowed
	# but don't try to parse it further into query, fragment etc.
	# We also include all unicode characters considered "letters" since it's likely someone might
	# put a ö or something in a path and copy-paste it from their browser URL bar which renders it
	# like that even though it's encoded when actually sent as a URL.
	# Restricting this to letters prevents things like non-breaking spaces causing problems.
	# For the same reason we also allow {} and [] which seem to show up often in paths.
	(?P<path> / [\w!#$%&'()*+,./:;=?@_~{}\[\]-]* )?
""", re.VERBOSE | re.IGNORECASE)


_IMAGE_LINKS_RUNNING = KeyedGroup()
def ensure_image_links(base_dir, text):
	"""Find any image or video links in the text and download them if we don't have them already.
	This happens in the background and errors are ignored."""
	media_dir = os.path.join(base_dir, "media")

	def get_url(url):
		try:
			try:
				download_media(url, media_dir)
			except FailedResponse:
				# We got a 404 or similar.
				# Attempt to remove any stray punctuation from the url and try again.
				# We only try this once.
				if url.endswith("..."):
					url = url[:-3]
				elif not url[-1].isalnum():
					url = url[:-1]
				else:
					# No puncuation found, let the original result stand
					raise
				download_media(url, media_dir)
		except WrongContent as e:
			logging.info(f"Ignoring non-media link {url}: {e}")
		except Rejected as e:
			logging.warning(f"Rejected dangerous link {url}: {e}")
		except Exception:
			logging.warning(f"Unable to fetch link {url}", exc_info=True)

	for match in URL_REGEX.finditer(text):
		# Don't match on bare hostnames with no scheme AND no path. ie.
		#   http://example.com SHOULD match
		#   example.com/foo SHOULD match
		#   example.com SHOULD NOT match
		# Otherwise we get a false positive every time someone says "fart.wav" or similar.
		if match.group("scheme") is None and match.group("path") is None:
			continue
		url = match.group(0)
		key = (media_dir, url)
		_IMAGE_LINKS_RUNNING.spawn(key, get_url, url)


def write_batch(path, batch_time, messages, size_histogram=None):
	"""Batches are named PATH/YYYY-MM-DDTHH/MM:SS-HASH.json"""
	output = (format_batch(messages) + '\n').encode('utf-8')
	if size_histogram is not None:
		size_histogram.observe(len(output))
	hash = base64.b64encode(hashlib.sha256(output).digest(), b"-_").decode().rstrip("=")
	hour = datetime.utcfromtimestamp(batch_time).strftime("%Y-%m-%dT%H")
	time = datetime.utcfromtimestamp(batch_time).strftime("%M:%S")
	filename = os.path.join(hour, "{}-{}.json".format(time, hash))
	filepath = os.path.join(path, filename)
	if os.path.exists(filepath):
		logging.debug("Not writing batch {} - already exists.".format(filename))
	else:
		atomic_write(filepath, output)
		logging.info("Wrote batch {}".format(filepath))
	return filepath


def merge_all(path, interval=None, stopping=None):
	"""Repeatedly scans the batch directory for batch files with the same batch time, and merges them.
	By default, returns once it finds no duplicate files.
	If interval is given, re-scans after that number of seconds.
	If a gevent.event.Event() is passed in as stopping arg, returns when that event is set.
	"""
	if stopping is None:
		# nothing will ever set this, but it's easier to not special-case it everywhere
		stopping = gevent.event.Event()
	while not stopping.is_set():
		start = monotonic()
		merges_done = 0
		# loop until no changes
		while True:
			logging.debug("Scanning for merges")
			by_time = {}
			for hour in listdir(path):
				for name in listdir(os.path.join(path, hour)):
					if not name.endswith(".json"):
						continue
					min_sec = name.split("-")[0]
					timestamp = "{}:{}".format(hour, min_sec)
					by_time[timestamp] = by_time.get(timestamp, 0) + 1
			if not any(count > 1 for timestamp, count in by_time.items()):
				logging.info("All batches are merged")
				break
			for timestamp, count in by_time.items():
				if count > 1:
					logging.info("Merging {} batches at time {}".format(count, timestamp))
					batch_time = timegm(time.strptime(timestamp, "%Y-%m-%dT%H:%M:%S"))
					merge_batch_files(path, batch_time)
					merges_done += 1
		duration = monotonic() - start
		merge_pass_duration.observe(duration)
		merge_pass_merges.observe(merges_done)
		if interval is None:
			# one-shot
			break
		remaining = interval - duration
		if remaining > 0:
			logging.debug("Waiting {}s for next merge scan".format(remaining))
			stopping.wait(remaining)


def merge_batch_files(path, batch_time):
	"""For the given batch time, merges all the following messages:
	- From batch files at that time
	- From batch files for the previous batch time
	- From batch files for the following batch time
	and writes up to 3 batch files (one for each time) to replace them.
	"""
	# A note on race conditions:
	# Suppose two processes attempt to merge the same batch at the same time.
	# The critical section consists of:
	# 1. Reading the old batch files
	# 2. Writing the new batch files
	# 3. Deleting the old batch files
	# Crucially, we don't delete any data until we've written a replacement,
	# and we don't delete any data that we didn't just incorporate into a new file.
	# This might cause doubling up of data, eg. version A -> version B but also
	# version A -> version C, but the end result will be that both B and C exist
	# and will then be merged later.

	messages = []
	batch_files = [
		batch_file
		for time in [batch_time, batch_time - BATCH_INTERVAL, batch_time + BATCH_INTERVAL]
		for batch_file in get_batch_files(path, time)
	]
	for batch_file in batch_files:
		with open(batch_file) as f:
			batch = f.read()
		batch = [json.loads(line) for line in batch.strip().split("\n")]
		messages = merge_messages(messages, batch)

	by_time = {}
	for message in messages:
		batch_time = int(message['time'] / BATCH_INTERVAL) * BATCH_INTERVAL
		by_time.setdefault(batch_time, []).append(message)

	written = []
	for batch_time, batch in by_time.items():
		written.append(write_batch(path, batch_time, batch))

	for batch_file in batch_files:
		# don't delete something we just (re-)wrote
		if batch_file not in written:
			os.remove(batch_file)


def main(nick, oauth_token_path, *channels, base_dir='/mnt', name=None, merge_interval=60, metrics_port=8008, download_media=False):
	with open(oauth_token_path) as f:
		oauth_token = f.read()
	# To ensure uniqueness even if multiple instances are running on the same host,
	# also include a random slug
	if name is None:
		name = socket.gethostname()
	slug = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(5))
	name = "{}.{}".format(name, slug)

	stopping = gevent.event.Event()
	gevent.signal_handler(signal.SIGTERM, stopping.set)

	mergers = [
		gevent.spawn(merge_all,
			os.path.join(base_dir, channel, "chat"),
			interval=merge_interval,
			stopping=stopping
		) for channel in channels
	]

	prom.start_http_server(metrics_port)

	logging.info("Starting")
	for index in count():
		# To ensure uniqueness between clients, include a client number
		archiver = Archiver("{}.{}".format(name, index), base_dir, channels, nick, oauth_token, download_media)
		archive_worker = gevent.spawn(archiver.run)
		workers = mergers + [archive_worker]
		# wait for either graceful exit, error, or for a signal from the archiver that a reconnect was requested
		gevent.wait([stopping, archiver.got_reconnect] + workers, count=1)
		if stopping.is_set():
			archiver.stop()
			for worker in workers:
				worker.get()
			break
		# if got reconnect, discard the old archiver (we don't care even if it fails after this)
		# and make a new one
		if archiver.got_reconnect.is_set():
			logging.info("Got RECONNECT, creating new client while waiting for old one to finish")
			continue
		# the only remaining case is that something failed. stop everything and re-raise.
		logging.warning("Stopping due to worker dying")
		stopping.set()
		archiver.stop()
		for worker in workers:
			worker.join()
		# at least one of these should raise
		for worker in workers:
			worker.get()
		assert False, "Worker unexpectedly exited successfully"
	logging.info("Gracefully stopped")
