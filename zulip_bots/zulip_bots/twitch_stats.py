
"""
This bot watches twitch APIs for a given channel,
saving data on viewership numbers, predictions and polls.
"""

import json
import logging
import random
import string
import time
from datetime import datetime

import argh
import prometheus_client as prom
from websockets.sync.client import connect

from .config import common_setup

logger = logging.getLogger(__name__)


twitch_stats_messages = prom.Counter(
	'twitch_stats_messages',
	'Number of twitch_stats messages received',
	['channel_id', 'topic', 'message_type'],
)

twitch_stats_last_message_received = prom.Gauge(
	'twitch_stats_last_message_received',
	'Timestamp of the last time a message was received',
	['channel_id', 'topic', 'message_type'],
)

twitch_stats_message_lag = prom.Gauge(
	'twitch_stats_message_lag',
	'Time difference between server time and local server for latest message',
	['channel_id', 'topic', 'message_type'],
)

twitch_stats_viewers = prom.Gauge(
	'twitch_stats_viewers',
	'How many stream viewers twitch reports on the stream',
	['channel_id'],
)


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


def main(output_file, *channel_ids, metrics_port=8019):
	common_setup(metrics_port)
	for msg in stream(channel_ids):
		with open(output_file, 'a') as f:
			f.write(json.dumps(msg) + '\n')
		labels = msg["channel_id"], msg["topic"], msg["message"].get("type", "UNKNOWN")
		twitch_stats_messages.labels(*labels).inc()
		twitch_stats_last_message_received.labels(*labels).set(msg["received_at"])
		if msg["message"].get("type") == "viewcount":
			try:
				twitch_stats_message_lag.labels(*labels).set(msg["received_at"] - msg["message"]["server_time"])
				twitch_stats_viewers.labels(msg["channel_id"]).set(msg["message"]["viewers"])
			except Exception:
				logging.warning(f"Could not process viewcount message {msg!r}", exc_info=True)


if __name__ == '__main__':
	argh.dispatch_command(main)
