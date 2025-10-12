
import json
import logging
import random
import string
import time
from datetime import datetime

import argh
from websockets.sync.client import connect

logger = logging.getLogger(__name__)


def make_id():
	return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(21))


def message(type, **data):
	now = datetime.utcnow().strftime("%FT%TZ")
	return dict(id=make_id(), type=type, timestamp=now, **data)


def subscribe(topic, channel_id):
	sub_id = make_id()
	return sub_id, message(type="subscribe", subscribe={
		"id": sub_id,
		"type": "pubsub",
		"pubsub": {"topic": f"{topic}.{channel_id}"},
	})


KNOWN_TOPICS = [
	"video-playback-by-id", # view counts
	"predictions-channel-v1",
	"polls",
]


def stream(channel_ids):
	with connect("wss://hermes.twitch.tv/v1?clientId=kimne78kx3ncx6brgo4mv6wki5h1ko") as ws:
		subscriptions = {}
		for channel_id in channel_ids:
			for topic in KNOWN_TOPICS:
				sub_id, msg = subscribe(topic, channel_id)
				subscriptions[sub_id] = topic, channel_id
				logger.info(f"Sending message: {msg}")
				ws.send(json.dumps(msg))
		while True:
			msg = json.loads(ws.recv())
			logger.info(f"Got messasge: {msg}")
			if msg.get("type") != "notification":
				continue
			msg = msg["notification"]
			sub_id = msg.get("subscription", {}).get("id")
			topic, channel_id = subscriptions.get(sub_id, (None, None))
			if msg.get("type") != "pubsub":
				continue
			msg = json.loads(msg["pubsub"])
			yield {
				"topic": topic,
				"channel_id": channel_id,
				"received_at": time.time(),
				"message": msg,
			}


def main(output_file, *channel_ids):
	logging.basicConfig(level="INFO")
	for msg in stream(channel_ids):
		with open(output_file, 'a') as f:
			f.write(json.dumps(msg) + '\n')


if __name__ == '__main__':
	argh.dispatch_command(main)
