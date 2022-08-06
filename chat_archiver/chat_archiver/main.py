
import base64
import errno
import hashlib
import json
import logging
import os
import signal
import socket
import time
from calendar import timegm
from datetime import datetime
from itertools import count
from uuid import uuid4

import gevent.event
import gevent.queue

from common import ensure_directory

from girc import Client

# How long each batch is
BATCH_INTERVAL = 60

# These are known to arrive up to 10s after their actual time
DELAYED_COMMANDS = [
	"JOIN",
	"PART",
]

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
# Worst case if too low: multiple output files for same batch that need merging later
MAX_SERVER_LAG = 30

# When guessing when a non-timestamped event occurred, pad the possible range
# by up to this amount before and after our best guess
ESTIMATED_TIME_PADDING = 5


class Archiver(object):
	def __init__(self, name, base_dir, channel, nick, oauth_token):
		self.logger = logging.getLogger(type(self).__name__).getChild(channel)
		self.name = name
		self.messages = gevent.queue.Queue()
		self.path = os.path.join(base_dir, channel, "chat")
		
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
		self.client.channel('#{}'.format(channel)).join()

	def run(self):
		# wait for twitch to send the initial ROOMSTATE for the room we've joined.
		# everything preceeding this message is per-connection stuff we don't care about.
		# once we get it, we register the handler to put everything following onto the
		# message queue.
		@self.client.handler(command='ROOMSTATE', sync=True)
		def register_real_handler(client, message):
			self.client.handler(lambda c, m: self.messages.put(m), sync=True)
			self.logger.info("Client started")
			return True

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
		# {batch time: [messages]}
		batches = {}

		while not (self.stopping.is_set() and self.messages.empty()):
			# wait until we either have a message, are stopping, or a batch can be closed
			if batches:
				next_batch_close = min(batches.keys()) + BATCH_INTERVAL + MAX_SERVER_LAG
				self.logger.debug("Next batch close at {} (batch times: {})".format(next_batch_close, batches.keys()))
				timeout = max(0, next_batch_close - time.time())
			else:
				timeout = None
			self.logger.debug("Waiting up to {} for message or stop".format(timeout))
			gevent.wait([gevent.spawn(self.messages.peek), self.stopping], count=1, timeout=timeout)

			# close any closable batches
			now = time.time()
			for batch_time, messages in list(batches.items()):
				if now >= batch_time + BATCH_INTERVAL + MAX_SERVER_LAG:
					del batches[batch_time]
					write_batch(self.path, batch_time, messages)

			# consume a message if any
			try:
				message = self.messages.get(block=False)
			except gevent.queue.Empty:
				continue

			if message.command not in COMMANDS:
				self.logger.info("Skipping non-whitelisted command: {}".format(message.command))
				continue

			self.logger.debug("Got message: {}".format(message))
			data = {
				attr: getattr(message, attr)
				for attr in ('command', 'params', 'sender', 'user', 'host', 'tags')
			}
			data['receivers'] = {self.name: message.received_at}
			self.logger.debug("Got message: {}".format(data))

			if data['tags'] and 'tmi-sent-ts' in data['tags']:
				# explicit server time is available
				timestamp = int(data['tags']['tmi-sent-ts']) / 1000. # original is int ms
				last_timestamped_message = message
				last_server_time = timestamp
				time_range = 0
				self.logger.debug("Message has exact timestamp: {}".format(timestamp))
				# check for any non-timestamped messages which we now know must have been
				# before this message. We need to check this batch and the previous.
				batch_time = int(timestamp / BATCH_INTERVAL) * BATCH_INTERVAL
				for batch in (batch_time, batch_time - BATCH_INTERVAL):
					for msg in batches.get(batch, []):
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
				# might have happened 10s sooner than otherwise indicated.
				timestamp -= 10
				time_range += 10

			self.logger.debug("Message time determined as {} + up to {}".format(timestamp, time_range))
			data['time'] = timestamp
			data['time_range'] = time_range
			batch_time = int(timestamp / BATCH_INTERVAL) * BATCH_INTERVAL
			batches.setdefault(batch_time, []).append(data)

		# Close any remaining batches
		for batch_time, messages in batches.items():
			write_batch(self.path, batch_time, messages)

		self.client.wait_for_stop() # re-raise any errors
		self.logger.info("Client stopped")

	def stop(self):
		self.client.stop()


def write_batch(path, batch_time, messages):
	"""Batches are named PATH/YYYY-MM-DDTHH/MM:SS-HASH.json"""
	output = (format_batch(messages) + '\n').encode('utf-8')
	hash = base64.b64encode(hashlib.sha256(output).digest(), b"-_").decode().rstrip("=")
	hour = datetime.utcfromtimestamp(batch_time).strftime("%Y-%m-%dT%H")
	time = datetime.utcfromtimestamp(batch_time).strftime("%M:%S")
	filename = os.path.join(hour, "{}-{}.json".format(time, hash))
	filepath = os.path.join(path, filename)
	if os.path.exists(filepath):
		logging.info("Not writing batch {} - already exists.".format(filename))
	else:
		temppath = "{}.{}.temp".format(filepath, uuid4())
		ensure_directory(filepath)
		with open(temppath, 'wb') as f:
			f.write(output)
		os.rename(temppath, filepath)
		logging.info("Wrote batch {}".format(filepath))
	return filepath


def format_batch(messages):
	# We need to take some care to have a consistent ordering and format here.
	# We use a "canonicalised JSON" format, which is really just whatever the python encoder does,
	# with compact separators.
	messages = [
		(message, json.dumps(message, separators=(',', ':')))
		for message in messages
	]
	# We sort by timestamp, then timestamp range, then if all else fails, lexiographically
	# on the encoded representation.
	messages.sort(key=lambda item: (item[0]['time'], item[0]['time_range'], item[1]))
	return "\n".join(line for message, line in messages)


def get_batch_files(path, batch_time):
	"""Returns list of batch filepaths for a given batch time"""
	hour = datetime.utcfromtimestamp(batch_time).strftime("%Y-%m-%dT%H")
	time = datetime.utcfromtimestamp(batch_time).strftime("%M:%S")
	hourdir = os.path.join(path, hour)
	# return [] if dir doesn't exist
	try:
		files = os.listdir(hourdir)
	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		return []
	return [
		os.path.join(hourdir, name)
		for name in files
		if name.startswith(time) and name.endswith(".json")
	]


def merge_all(path):
	"""Repeatedly scans the batch directory for batch files with the same batch time, and merges them.
	Returns once it finds no duplicate files."""
	while True:
		by_time = {}
		for hour in os.listdir(path):
			for name in os.listdir(os.path.join(path, hour)):
				if not name.endswith(".json"):
					continue
			time = "-".join(name.split("-")[:3])
			timestamp = "{}:{}".format(hour, time)
			by_time[timestamp] = by_time.get(timestamp, 0) + 1
		if not any(count > 1 for timestamp, count in by_time.items()):
			break
		for timestamp, count in by_time.items():
			if count > 1:
				logging.info("Merging {} batches at time {}".format(count, timestamp))
				batch_time = timegm(time.strptime(timestamp, "%Y-%m-%dT%H:%M:%S"))
				merge_batch_files(path, batch_time)


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

def merge_messages(left, right):
	"""Merges two lists of messages into one merged list.
	This operation should be a CRDT, ie. all the following hold:
	- associative: merge(merge(A, B), C) == merge(A, merge(B, C))
	- commutitive: merge(A, B) == merge(B, A)
	- reflexive: merge(A, A) == A
	This means that no matter what order information from different sources
	is incorporated (or if sources are repeated), the results should be the same.
	"""
	# An optimization - if either size is empty, return the other side without processing.
	if not left:
		return right
	if not right:
		return left

	# Calculates intersection of time range of both messages, or None if they don't overlap
	def overlap(a, b):
		range_start = max(a['time'], b['time'])
		range_end = min(a['time'] + a['time_range'], b['time'] + b['time_range'])
		if range_end < range_start:
			return None
		return range_start, range_end - range_start
		
	# Returns merged message if two messages are compatible with being the same message,
	# or else None.
	def merge_message(a, b):
		o = overlap(a, b)
		if o and all(
			a.get(k) == b.get(k)
			for k in set(a.keys()) | set(b.keys())
			if k not in ("receivers", "time", "time_range")
		):
			receivers = a["receivers"] | b["receivers"]
			# Error checkdng - make sure no receiver timestamps are being overwritten.
			# This would indicate we're merging two messages recieved at different times
			# by the same recipient.
			for k in receivers.keys():
				for old in (a, b):
					if k in old and old[k] != receivers[k]:
						raise ValueError(f"Merge would merge two messages with different recipient timestamps: {a}, {b}")
			return a | {
				"time": o[0],
				"time_range": o[1],
				"receivers": receivers,
			}
		return None

	# Match things with identical ids first, and collect unmatched into left and right lists
	by_id = {}
	unmatched = [], []
	for messages, u in zip((left, right), unmatched):
		for message in messages:
			id = (message.get('tags') or {}).get('id')
			if id:
				by_id.setdefault(id, []).append(message)
			else:
				u.append(message)

	result = []
	for id, messages in by_id.items():
		if len(messages) == 1:
			logging.debug(f"Message with id {id} has no match")
			result.append(messages[0])
		else:
			merged = merge_message(*messages)
			if merged is None:
				raise ValueError(f"Got two non-matching messages with id {id}: {messages[0]}, {messages[1]}")
			logging.debug(f"Merged messages with id {id}")
			result.append(merged)

	# For time-range messages, pair off each one in left with first match in right,
	# and pass through anything with no matches.
	left_unmatched, right_unmatched = unmatched
	for message in left_unmatched:
		for other in right_unmatched:
			merged = merge_message(message, other)
			if merged:
				logging.debug(
					"Matched {m[command]} message {a[time]}+{a[time_range]} & {b[time]}+{b[time_range]} -> {m[time]}+{m[time_range]}"
					.format(a=message, b=other, m=merged)
				)
				right_unmatched.remove(other)
				result.append(merged)
				break
		else:
			logging.debug("No match found for {m[command]} at {m[time]}+{m[time_range]}".format(m=message))
			result.append(message)
	for message in right_unmatched:
		logging.debug("No match found for {m[command]} at {m[time]}+{m[time_range]}".format(m=message))
		result.append(message)

	return result


def main(channel, nick, oauth_token_path, base_dir='/mnt', name=None):
	with open(oauth_token_path) as f:
		oauth_token = f.read()
	# To ensure uniqueness even if multiple instances are running on the same host,
	# also include our pid
	if name is None:
		name = socket.gethostname()
	name = "{}.{}".format(name, os.getpid())

	stopping = gevent.event.Event()
	gevent.signal_handler(signal.SIGTERM, stopping.set)

	logging.info("Starting")
	for index in count():
		# To ensure uniqueness between clients, include a client number
		archiver = Archiver("{}.{}".format(name, index), base_dir, channel, nick, oauth_token)
		worker = gevent.spawn(archiver.run)
		# wait for either graceful exit, error, or for a signal from the archiver that a reconnect was requested
		gevent.wait([stopping, worker, archiver.got_reconnect], count=1)
		if stopping.is_set():
			archiver.stop()
			worker.get()
			break
		# if got reconnect, discard the old archiver (we don't care even if it fails after this)
		# and make a new one
		if archiver.got_reconnect.is_set():
			logging.info("Got RECONNECT, creating new client while waiting for old one to finish")
			continue
		# the only remaining case is that the worker failed, re-raise
		worker.get()
		assert False, "Not stopping, but worker exited successfully"
	logging.info("Gracefully stopped")
