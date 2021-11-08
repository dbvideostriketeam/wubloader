
import base64
import hashlib
import json
import logging
import os
import signal
import socket
import time
from datetime import datetime
from uuid import uuid4

import gevent.event
import gevent.queue

from common import ensure_directory

from girc import Client


class Archiver(object):
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

	# How long each batch is
	BATCH_INTERVAL = 60

	# Assume we're never more than this amount of time behind the server time
	# Worst case if too low: multiple output files for same batch that need merging later
	MAX_SERVER_LAG = 30

	# When guessing when a non-timestamped event occurred, pad the possible range
	# by up to this amount before and after our best guess
	ESTIMATED_TIME_PADDING = 5

	def __init__(self, name, base_dir, channel, nick, oauth_token):
		self.logger = logging.getLogger(type(self).__name__).getChild(channel)
		self.name = name
		self.messages = gevent.queue.Queue()
		self.path = os.path.join(base_dir, channel)
		
		self.stopping = gevent.event.Event()
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
			return True

		self.client.start()

		last_server_time = None
		last_timestamped_message = None
		# {batch time: [messages]}
		batches = {}

		while not self.stopping.is_set():
			# wait until we either have a message, are stopping, or a batch can be closed
			if batches:
				next_batch_close = min(batches.keys()) + self.BATCH_INTERVAL + self.MAX_SERVER_LAG
				self.logger.debug("Next batch close at {} (batch times: {})".format(next_batch_close, batches.keys()))
				timeout = max(0, next_batch_close - time.time())
			else:
				timeout = None
			self.logger.debug("Waiting up to {} for message or stop".format(timeout))
			gevent.wait([gevent.spawn(self.messages.peek), self.stopping], count=1, timeout=timeout)

			# close any closable batches
			now = time.time()
			for batch_time, messages in list(batches.items()):
				if now >= batch_time + self.BATCH_INTERVAL + self.MAX_SERVER_LAG:
					del batches[batch_time]
					self.write_batch(batch_time, messages)

			# consume a message if any
			try:
				message = self.messages.get(block=False)
			except gevent.queue.Empty:
				continue

			if message.command not in self.COMMANDS:
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
				batch_time = int(timestamp / self.BATCH_INTERVAL) * self.BATCH_INTERVAL
				for batch in (batch_time, batch_time - self.BATCH_INTERVAL):
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
				timestamp = est_server_time - self.ESTIMATED_TIME_PADDING
				time_range = 2 * self.ESTIMATED_TIME_PADDING
				# if previously timestamped message falls within this range, we know this message
				# came after it
				timestamp = max(timestamp, last_server_time)
			else:
				# we have no idea what the server time is, so we guess as 2x the normal padding
				# starting from local time.
				timestamp = time.time() - 2 * self.ESTIMATED_TIME_PADDING
				time_range = 3 * self.ESTIMATED_TIME_PADDING

			if data['command'] in self.DELAYED_COMMANDS:
				# might have happened 10s sooner than otherwise indicated.
				timestamp -= 10
				time_range += 10

			self.logger.debug("Message time determined as {} + up to {}".format(timestamp, time_range))
			data['time'] = timestamp
			data['time_range'] = time_range
			batch_time = int(timestamp / self.BATCH_INTERVAL) * self.BATCH_INTERVAL
			batches.setdefault(batch_time, []).append(data)

		# Close any remaining batches
		for batch_time, messages in batches.items():
			self.write_batch(batch_time, messages)

		self.client.wait_for_stop() # re-raise any errors

	def write_batch(self, batch_time, messages):
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
		output = ("\n".join(line for message, line in messages) + "\n").encode("utf-8")
		hash = base64.b64encode(hashlib.sha256(output).digest(), b"-_").decode().rstrip("=")
		time = datetime.utcfromtimestamp(batch_time).strftime("%Y-%m-%dT%H:%M:%S")
		filename = "{}-{}.json".format(time, hash)
		filepath = os.path.join(self.path, filename)
		temppath = "{}.{}.temp".format(filepath, uuid4())
		ensure_directory(filepath)
		with open(temppath, 'wb') as f:
			f.write(output)
		os.rename(temppath, filepath)
		self.logger.info("Wrote batch {}".format(filepath))

	def stop(self):
		self.client.stop()


def main(channel, nick, oauth_token_path, base_dir='/mnt'):
	with open(oauth_token_path) as f:
		oauth_token = f.read()
	name = socket.gethostname()

	archiver = Archiver(name, base_dir, channel, nick, oauth_token)

	gevent.signal_handler(signal.SIGTERM, archiver.stop)

	logging.info("Starting")
	archiver.run()
	logging.info("Gracefully stopped")
