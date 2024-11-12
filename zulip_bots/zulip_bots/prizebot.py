
from collections import namedtuple
import json
import time
import re

import argh
import requests
from bs4 import BeautifulSoup

from .config import get_config
from .zulip import Client

Prize = namedtuple("Prize", ["id", "link", "type", "title", "state", "result"])


def get_prizes(type):
	resp = requests.get(f"https://desertbus.org/2024/prizes/{type}", {"User-Agent": ""})
	resp.raise_for_status()
	html = BeautifulSoup(resp.content.decode(), "html.parser")

	main = html.body.main
	prizes = []
	for a in main.find_all("a"):
		# look for prize links
		match = re.match("^/\d+/prize/([A-Z]+)$", a["href"])
		if not match:
			continue
		# skip image links
		if a.find("img") is not None:
			continue
		# skip "See More" link
		if "See More >" in a.string:
			continue
		id = match.group(1)
		title = a.string
		div = a.parent.parent
		current = div.find_all("div", recursive=False)[1].contents[0].strip()
		result = None
		if current.startswith("Starts"):
			state = "pending"
		elif current.startswith("High Bid"):
			state = "active"
		elif current.startswith("Entries open"):
			state = "active"
		elif current.startswith("Giveaway closed"):
			state = "active"
		elif current.startswith("Winner"):
			state = "sold"
			result = " - ".join([
				"".join(d.strings).strip() for d in div.find_all("div", recursive=False)
				if "text-brand-green" in d["class"]
			])
		else:
			state = "unknown"
		prizes.append(Prize(id, a["href"], type, title, state, result))
	return prizes


def send_message(client, prize, test=False):
	message = f"[{prize.title}]({prize.link}) {prize.result}"
	if prize.type == "giveaway":
		message += "\n@*editors* Remember to go back and edit the giveaway video"
	if test:
		print(message)
	else:
		client.send_to_stream("bot-spam", "Prize Winners", message)


def main(config_file, test=False, all=False, once=False, interval=60):
	"""
	Config:
		url, email, api_key: zulip creds
		state: path to state file
	"""
	config = get_config(config_file)
	with open(config['state']) as f:
		# state is {id: last seen state}
		state = json.load(f)
	client = Client(config['url'], config['email'], config['api_key'])
	while True:
		start = time.time()
		for type in ('live', 'silent', 'giveaway'):
			prizes = get_prizes(type)
			for prize in prizes:
				logging.info(f"Got prize: {prize}")
				if prize.state == "sold" and (all or state.get(prize.id, "sold") != "sold"):
					send_message(client, prize, test=test)
				state[prize.id] = prize.state
		if not test:
			with open(config['state'], 'w') as f:
				f.write(json.dumps(state) + '\n')
		if once:
			break
		remaining = start + interval - time.time()
		if remaining > 0:
			time.sleep(remaining)


if __name__ == '__main__':
	argh.dispatch_command(main)
