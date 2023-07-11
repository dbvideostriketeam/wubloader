
import json
import logging

import requests

session = requests.Session()

class Client(object):
	def __init__(self, base_url, email, api_key):
		self.base_url = base_url
		self.email = email
		self.api_key = api_key

	def request(self, method, *path, **params):
		if method == 'GET':
			args = {"params": params}
		else:
			args = {"data": {
				k: v if isinstance(v, str) else json.dumps(v)
				for k, v in params.items()
			}}  
		url = "/".join([self.base_url, "api/v1"] + list(map(str, path)))
		resp = session.request(method, url, auth=(self.email, self.api_key), **args)
		if not resp.ok:
			logging.info(repr(params))
			logging.info(f"Got {resp.status_code} for {url}: {resp.text}")
		resp.raise_for_status()
		return resp.json()

	def send_to_stream(self, stream, topic, content):
		return self.request("POST", "messages",
			type="stream",
			to=stream,
			topic=topic,
			content=content,
		)
