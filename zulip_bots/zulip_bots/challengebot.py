
import json
import time

import argh
import requests

from common.zulip import Client

from .config import common_setup, get_config

def get_challenges(url, api_key):
	resp = requests.get(url, headers={
		"Authorization": api_key,
		"User-Agent": "challengebot",
	})
	resp.raise_for_status()
	return resp.json()["challenges"]

def main(config_file, interval=60, metrics_port=8020, test=False, once=False, first_run=False):
	"""
	Config:
		zulip: url, email, api_key
		challenge_api: url, api_key
		state: path to state file
	"""
	common_setup(metrics_port)
	config = get_config(config_file)
	with open(config['state']) as f:
		# state is {id: {}}
		state = json.load(f)
	client = Client(config['zulip']['url'], config['zulip']['email'], config['zulip']['api_key'])
	while True:
		start = time.time()
		challenges = get_challenges(**config["challenge_api"])
		for challenge in challenges[::-1]:
			if challenge["id"] in state:
				continue
			text = challenge["description"]
			message = f"```quote\n{text}\n```"
			if test:
				print(message)
			elif not first_run:
				client.send_to_stream("editors", "Completed Challenges", message)
			state[challenge["id"]] = challenge
		if not test:
			with open(config['state'], 'w') as f:
				f.write(json.dumps(state) + '\n')
		if once:
			break
		first_run = False
		remaining = start + interval - time.time()
		if remaining > 0:
			time.sleep(remaining)


if __name__ == '__main__':
	argh.dispatch_command(main)
