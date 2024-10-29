
import json
import time

import argh
import requests

from .config import get_config
from .zulip import Client


def get_prizes(type):
	resp = requests.get("https://desertbus.org/wapi/prizes/{}".format(type))
	resp.raise_for_status()
	return resp.json()['prizes']


def send_message(client, prize, test=False, giveaway=False):
	message = "[{title}](https://desertbus.org/prize/{id}) won by {bidder} - raised ${bid:.2f}".format(**prize)
	if giveaway:
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
		for type in ('live_auction', 'silent_auction', 'giveaway'):
			prizes = get_prizes(type)
			for prize in prizes:
				id = str(prize['id'])
				if prize['state'] == "sold" and (all or state.get(id, "sold") != "sold"):
					send_message(client, prize, test=test, giveaway=(type == "giveaway"))
				state[id] = prize['state']
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
