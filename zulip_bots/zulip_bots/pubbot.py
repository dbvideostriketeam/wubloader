
import json
import logging
import os
import socket
import time

from .config import get_config
from .zulip import Client

import requests
session = requests.Session()

def stream(channels):
	channels = ",".join(channels)
	tt = 0
	tr = 0
	while True:
		resp = session.get(f"https://ps8.pndsn.com/v2/subscribe/sub-cbd7f5f5-1d3f-11e2-ac11-877a976e347c/{channels}/0",
			params={
				"tt": tt,
				"tr": tr,
			},
		)
		resp.raise_for_status()
		data = resp.json()
		for msg in data.get("m", []):
			yield msg
		tt = data["t"]["t"]
		tr = data["t"]["r"]


giveaway_cache = [None, None]
def get_giveaway():
	REFRESH_RISING = 30
	REFRESH_FALLING = 300
	t, g = giveaway_cache
	now = time.time()
	timeout = REFRESH_RISING if g is None else REFRESH_FALLING
	if t is None or now - t > timeout:
		resp = session.get("https://desertbus.org/wapi/currentGiveaway")
		resp.raise_for_status()
		g = resp.json()["giveaway"]
		giveaway_cache[0] = t
		giveaway_cache[1] = g
	return g


def main(conf_file, message_log_file, name=socket.gethostname()):
	"""Config:
		zulip_url
		zulip_email
		zulip_api_key
		total_id: id for donation total channel
		prize_ids: list of ids for prizes to watch bids for
	"""
	logging.basicConfig(level="INFO")

	config = get_config(conf_file)
	client = Client(config["zulip_url"], config["zulip_email"], config["zulip_api_key"])

	message_log = open(message_log_file, "a")
	def write_log(log):
		message_log.write(json.dumps(log) + '\n')

	write_log({
		"type": "startup",
		"host": name,
		"pid": os.getpid(),
		"time": time.time(),
	})

	total_channel = f"total:{config['total_id']}"
	channels = [total_channel] + [
		f"bid:{prize_id}" for prize_id in config["prize_ids"]
	]
	total = None
	for msg in stream(channels):
		log = {
			"type": "unknown",
			"host": name,
			"pid": os.getpid(),
			"time": time.time(),
			"message": msg,
		}

		try:
			try:
				message_time = float(msg["p"]["t"]) / 10000000
			except (KeyError, ValueError):
				message_time = None

			log["message_time"] = message_time

			if msg["c"] == total_channel:
				log["type"] == "total"
				increase = None if total is None else msg["d"] - total
				log["increase"] = increase
				increase_str = "" if increase is None else " (+${:.2f})".format(msg["d"] - total)
				giveaway = None
				entries_str = ""
				if increase is not None and giveaway is not None:
					amount = giveaway["amount"]
					if (increase + 0.005) % amount < 0.01:
						entries = int((increase + 0.005) / amount)
						log["giveaway_amount"] = amount
						log["giveaway_entries"] = entries
						entries_str = " ({} entries of ${:.2f})".format(entries, amount)
				logging.info("New donation total: {}{}{}".format(msg["d"], increase_str, entries_str))
				client.send_to_stream("bot-spam", "Donation Firehose", "Donation total is now ${:.2f}{}{}".format(msg["d"], increase_str, entries_str))
				if increase is not None and increase >= 500:
					client.send_to_stream("bot-spam", "Notable Donations", "Large donation of ${:.2f} (total ${:.2f}){}".format(increase, msg['d'], entries_str))
				total = msg["d"]

			elif msg["c"].startswith("bid:"):
				log["type"] = "prize"
				prize_id = msg["c"].removeprefix("bid:")
				log["prize_id"] = prize_id
				data = msg["d"]
				logging.info(f"Prize update for {prize_id}: {data}")
				if "name" in data and "amount" in data:
					log["bidder"] = data["name"]
					log["bid"] = data["amount"]
					client.send_to_stream(
						"bot-spam",
						"Bids",
						"At <time:{message_time}>, {data['name']} ({data['donorID']}) has the high bid of ${data['amount']:.2f} for prize [{prize_id}](https://desertbus.org/prize/{prize_id})",
					)

			else:
				logging.warning("Unknown message: {}".format(msg))
		except Exception:
			logging.exception(f"Failed to handle message {msg}")
			log["type"] = "error"

		write_log(log)


if __name__ == '__main__':
	import argh
	argh.dispatch_command(main)
