
"""
This bot polls the DB challenge API, posting any newly seen challenges to Zulip
so that editors know to go and link it to a video.
"""

import json
import logging
import time

import argh
import requests

from common.zulip import Client as ZulipClient
from common import website

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
		challenge_api_key
		state: path to state file
	"""
	common_setup(metrics_port)
	config = get_config(config_file)
	with open(config['state']) as f:
		# state is {id: {}}
		state = json.load(f)
	zulip = ZulipClient(config['zulip']['url'], config['zulip']['email'], config['zulip']['api_key'])
	web = website.Client(auth_token=config["challenge_api_key"])
	while True:
		start = time.time()
		challenges = web.challenges()
		for challenge in challenges[::-1]:
			if challenge["id"] in state:
				continue
			try:
				text = website.block_to_md(challenge["description"])
				message = f"```quote\n{text}\n```"
			except Exception:
				logging.warning(f"Failed to parse challenge: {challenge}", exc_info=True)
				message = f"Failed to parse challenge {challenge['id']}, see log"
			if test:
				print(message)
			elif not first_run:
				zulip.send_to_stream("editors", "Completed Challenges", message)
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
