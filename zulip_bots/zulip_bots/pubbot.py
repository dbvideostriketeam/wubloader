
import json
import logging
import os
import re
import socket
import time

from bs4 import BeautifulSoup

from common.zulip import Client

from .config import common_setup, get_config
from .prizebot import get_prizes

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


def get_current(channel):
	resp = session.get(f"https://pubsub.pubnub.com/history/sub-cbd7f5f5-1d3f-11e2-ac11-877a976e347c/{channel}/0/1")
	resp.raise_for_status()
	data = resp.json()
	return data[0] if data else None


giveaway_cache = [None, None]
def get_giveaway(year):
	REFRESH_RISING = 30
	REFRESH_FALLING = 300
	t, g = giveaway_cache
	now = time.time()
	timeout = REFRESH_RISING if g is None else REFRESH_FALLING
	if t is None or now - t > timeout:
		try:
			g = _get_giveaway(year)
		except Exception:
			logging.warning("Failed to fetch giveaway", exc_info=True)
		else:
			giveaway_cache[0] = t
			giveaway_cache[1] = g
	return giveaway_cache[1]


def _get_giveaway(year):
	resp = session.get(f"https://desertbus.org/{year}/donate", headers={"User-Agent": ""})
	resp.raise_for_status()
	html = BeautifulSoup(resp.content.decode(), "html.parser")
	island = html.find("astro-island", **{"component-export": "DonateForm"})
	if island is None:
		logging.warning("Could not find DonateForm astro-island in donate page")
		return None
	data = json.loads(island["props"])
	giveaways = data["giveaways"][1]
	if giveaways:
		return giveaways[0][1]["amount"][1] / 100.
	return None


prize_cache = {}
def get_prize_name(year, id):
	if id not in prize_cache:
		try:
			prize_cache[id] = _get_prize_name(year, id)
		except Exception:
			logging.warning(f"Failed to get prize title for {id}", exc_info=True)
			return "Unknown prize"
	return prize_cache[id]


def _get_prize_name(year, id):
	resp = requests.get(f"https://desertbus.org/{year}/prize/{id}", {"User-Agent": ""})
	resp.raise_for_status()
	html = BeautifulSoup(resp.content.decode(), "html.parser")
	div = html.body.main.find("div", **{"class": lambda cl: "text-brand-gold" in cl})
	# These divs have format "Silent Auction: NAME", "Giveaway: NAME", etc. Split after first ": ".
	return div.string.split(": ", 1)[-1].strip()


def find_winning_bids(year, amount):
	matches = []
	misses = []
	for prize in get_prizes(year, 'silent') + get_prizes(year, 'live'):
		if prize.state != "sold":
			misses.append(f"{prize.id} state {prize.state}")
			continue
		match = re.search(r" for (\$[0-9,.]+)", prize.result)
		if not match:
			misses.append(f"{prize.id} no match {prize.result!r}")
			continue
		try:
			bid = float(match.group(1).replace(",", ""))
		except ValueError:
			misses.append(f"{prize.id} misparse {match.group(1)!r}")
			continue
		if bid == amount:
			matches.append(prize)
	logging.info(f"{len(matches)} matched for {amount} in {year}, not matched: {', '.join(misses)}")
	return matches


def main(conf_file, message_log_file, name=socket.gethostname(), metrics_port=8015):
	"""Config:
		zulip_url
		zulip_email
		zulip_api_key
		year
		total_id: id for donation total channel
		prize_ids: list of ids for prizes to watch bids for
	"""
	common_setup(metrics_port)

	config = get_config(conf_file)
	client = Client(config["zulip_url"], config["zulip_email"], config["zulip_api_key"])
	year = config["year"]

	message_log = open(message_log_file, "a")
	def write_log(log):
		message_log.write(json.dumps(log) + '\n')
		message_log.flush()

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
	total = get_current(total_channel)
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
				log["type"] = "total"
				increase = None if total is None else msg["d"] - total
				log["increase"] = increase
				increase_str = "" if increase is None else " (+${:.2f})".format(msg["d"] - total)
				giveaway_amount = get_giveaway(year)
				entries_str = ""
				if increase is not None and giveaway_amount is not None:
					if (increase + 0.005) % giveaway_amount < 0.01:
						entries = int((increase + 0.005) / giveaway_amount)
						log["giveaway_amount"] = giveaway_amount
						log["giveaway_entries"] = entries
						entries_str = " ({} entries of ${:.2f})".format(entries, giveaway_amount)
				logging.info("New donation total: {}{}{}".format(msg["d"], increase_str, entries_str))
				total = msg["d"]
				if increase is not None and increase > 0:
					client.send_to_stream("firehose", "Donations", "Donation total is now ${:.2f}{}{}".format(msg["d"], increase_str, entries_str))
				if increase is not None and increase >= 500:
					try:
						matches = find_winning_bids(year, increase)
					except Exception:
						logging.warning("Failed to check bids for notable donation", exc_info=True)
						matches = []
					prize_str = ""
					if matches:
						prize_str = " (may be for {})".format(" or ".join(
							"[{}]({})".format(prize.title, prize.link)
							for prize in matches
						))
					client.send_to_stream("bot-spam", "Notable Donations", "Large donation of ${:.2f} (total ${:.2f}){}{}".format(increase, msg['d'], prize_str, entries_str))

			elif msg["c"].startswith("bid:"):
				log["type"] = "prize"
				prize_id = msg["c"].removeprefix("bid:")
				log["prize_id"] = prize_id
				prize_name = get_prize_name(year, prize_id)
				log["prize_name"] = prize_name
				data = msg["d"]
				logging.info(f"Prize update for {prize_id}: {data}")
				if "name" in data and "amount" in data:
					log["bidder"] = data["name"]
					amount = data["amount"] / 100
					log["bid"] = amount
					client.send_to_stream(
						"bot-spam",
						"Bids",
						f"At <time:{message_time}>, {data['name']} ({data['donorID']}) has the high bid of ${amount:.2f} for prize [{prize_name}](https://desertbus.org/prize/{prize_id})",
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
