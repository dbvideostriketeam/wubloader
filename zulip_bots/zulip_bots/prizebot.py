
"""
This bot watches the website pages for prizes, tracking their state and posting to zulip
when a prize becomes Sold. It also saves the info to a file as JSON.
It tracks the previously-seen state for each prize in a state file.

It also tracks and saves donations.
"""

from collections import namedtuple
import json
import logging
import os
import time

import argh

from common.zulip import Client as ZulipClient
from common.website import Client as WebClient

from .config import common_setup, get_config

Prize = namedtuple("Prize", ["id", "link", "type", "title", "state", "result"])


def prize_name(event, prize):
	url = f"https://desertbus.org/{event['url']}/prize/{prize['id']}"
	return f"[{prize["name"]}]({url})"


def sold_message(event, prize):
	name = prize_name(event, prize)
	winners = ", ".join(winner["display_name"] for winner in prize["winners"])
	raised = f"${prize['raised']['amount']}"
	if prize["type"] == "giveaway":
		return f"{name} won by {winners}, raised {raised}\n@*editors* Remember to go back and edit the giveaway video"
	else:
		return f"{name} won by {winners} for {raised}"


def giveaway_set(event, prize):
	name = prize_name(event, prize)
	amount = f"${prize["giveaway_amount"]}"
	time = lambda s: f"<time:{s}>"
	return f"{name} is being given away for {amount} from {time(prize['starts_at'])} to {time(prize['ends_at'])}"


def high_bid(event, prize):
	name = prize_name(event, prize)
	bid = prize["current_high_bid"]
	return f"At <time:{time.time()}>, {bid['name']} has the high bid of ${bid['amount']['amount']} for {name}"


def main(
	config_file,
	stream="bot-spam",
	firehose_stream="firehose",
	test=False,
	all=False,
	metrics_port=8017,
	log_file=None,
	event_id=None,
):
	"""
	Config:
		url, email, api_key: zulip creds
		state: path to state file
	"""
	common_setup(metrics_port)
	config = get_config(config_file)
	if os.path.exists(config["state"]):
		with open(config['state']) as f:
			# state is {prizes: {id: last seen prize json}}
			state = json.load(f)
	else:
		state = {"prizes": {}}
	if not test:
		zulip = ZulipClient(config['url'], config['email'], config['api_key'])
	website = WebClient(event_id=event_id)
	if log_file is not None:
		log_file = open(log_file, "a")
	event = website.event()

	def send(stream, topic, content):
		if test:
			print(f"{stream}->{topic}: {content}")
		else:
			zulip.send_to_stream(stream, topic, content)

	def log(data):
		if log_file is not None:
			log["time"] = time.time()
			log_file.write(json.dumps(data) + "\n")
			log_file.flush()

	def save_state():
		if not test:
			with open(config['state'], 'w') as f:
				f.write(json.dumps(state) + '\n')

	def process_prize(prize):
		log({"prize": prize})
		id = prize["id"]
		logging.info(f"Got prize (in state = {id in state}): {prize}")
		old = state["prizes"].get(id, {})

		# prize sold
		if prize["state"] == "sold" and (all or old.get("state") != "sold"):
			send(stream, "Prize Winners", sold_message(event, prize))

		# prize giveaway amount set
		if prize["giveaway_amount"] is not None and prize["giveaway_amount"] != old.get("giveaway_amount"):
			send(stream, "Bids", giveaway_set(event, prize))

		# prize bid
		if prize["current_high_bid"] is not None and prize["current_high_bid"] != old.get("current_high_bid"):
			send(stream, "Bids", high_bid(event, prize))

		state["prizes"][id] = prize

	def process_donation(donation):
		log({"donation": donation})

		message = f"{donation['display_name']} donated ${donation['amount']['amount']} at <time:{donation['processed_at']}>"
		amount = float(donation["amount"]["amount"])

		if amount >= 500:
			send(stream, "Notable Donations", message)
		send(firehose_stream, "Donations", message)

		state["donation_token"] = donation["token"]

	stream = website.event_stream()
	stream.subscribe_prizes()
	stream.subscribe_donations(last_seen=state.get("donation_token"))

	for prize in website.prizes():
		process_prize(prize)

	for message in stream.recv():
		if message.event == "prize":
			process_prize(message.payload)
		if message.event == "donation":
			process_donation(message.payload)

if __name__ == '__main__':
	argh.dispatch_command(main)
