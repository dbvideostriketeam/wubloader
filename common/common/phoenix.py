"""Client for Phoenix websockets"""

# Reference: https://phoenix.hexdocs.pm/writing_a_channels_client.html

if __name__ == '__main__':
	from gevent.monkey import patch_all
	patch_all()

from collections import namedtuple
from uuid import uuid4
import json
import logging

from websockets.sync.client import connect
import gevent


Message = namedtuple("Message", ["join_ref", "msg_ref", "topic", "event", "payload"])


def uuid():
	return str(uuid4())


class Client:
	def __init__(self, url, heartbeat_interval=10):
		"""URL needs to end in /websocket?vsn=2.0.0"""
		self.logger = logging.getLogger("phoenix").getChild(str(id(self)))
		self.logger.debug(f"Connecting to {url!r}")
		self.socket = connect(url)
		self.heartbeater = gevent.spawn(self._heartbeat, heartbeat_interval)

	def subscribe(self, topic, params={}):
		join_id, message_id = uuid(), uuid()
		self._send(Message(join_id, message_id, topic, "phx_join", params))
		return join_id, message_id

	def recv(self):
		"""Iterator that streams incoming events"""
		while True:
			if self.heartbeater.ready():
				try:
					self.heartbeater.get()
					assert False, "heartbeater should not return successfully"
				except Exception as e:
					raise Exception("Heartbeater failed") from e
			message = self.socket.recv()
			self.logger.debug(f"Recieved {message!r}")
			message = Message(*json.loads(message))
			if message.event == "phx_reply" and message.payload["status"] != "ok":
				raise Exception(f"Failed reply: {message!r}")
			yield message

	def _send(self, message):
		message = json.dumps(message)
		self.logger.debug(f"Sending {message!r}")
		self.socket.send(message)

	def _heartbeat(self, interval):
		while True:
			gevent.sleep(interval)
			self._send(Message(None, uuid(), "phoenix", "heartbeat", {}))


if __name__ == '__main__':
	import argh

	def parse_topic(arg):
		if "?" in arg:
			topic, params = arg.split("?", 1)
			params = dict(part.split("=", 1) for part in params.split(","))
		else:
			topic, params = arg, {}
		return topic, params

	@argh.arg("topics", nargs="*", metavar="TOPIC{,KEY=VALUE}", type=parse_topic)
	def main(url, topics, heartbeat_interval=10.):
		"""Basic debug client for phoenix sockets"""
		client = Client(url, heartbeat_interval=heartbeat_interval)
		for topic, params in topics:
			client.subscribe(topic, params)
		for msg in client.recv():
			print(msg)

	argh.dispatch_command(main)
