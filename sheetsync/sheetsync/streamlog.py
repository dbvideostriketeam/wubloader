
import json

import requests

class StreamLog():
	"""Client for Stream Log server"""

	def __init__(self, url, event_name, auth_token):
		self.url = url
		self.auth_token = auth_token
		self.session = requests.Session()

		self.event_id = self.request("GET", "event_by_name", event_name)["id"]

	def get_rows(self):
		"""Return a list of rows, where each row is a dict"""
		return self.request("GET", "event", self.event_id, "log")

	def write_value(self, row_id, key, value):
		"""Write key=value for the given row"""
		return self.request("POST", "entry", row_id, key, body=value)

	def request(self, method, *path, body=None):
		response = self.session.request(method, "/".join(("api", "v1") + path),
			data=body,
			headers={
				"Authorization": self.auth_token,
			},
		)
		response.raise_for_status()
		content = response.text
		if content:
			return json.loads(content)
		return None
