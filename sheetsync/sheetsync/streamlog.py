
import json

import requests

from common.dateutil import parse_utc_only

class StreamLogClient():
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


class StreamLogMiddleware:
	def __init__(self, client, bustime_start):
		self.client = client
		self.bustime_start = bustime_start
		# Maps DB column names to streamlog fields.
		self.column_map = {
			'event_start': 'start_time',
			'event_end': 'end_time',
			'category': 'entry_type',
			'description': 'description',
			'submitter_winner': 'submitter_or_winner',
			'poster_moment': 'poster_moment',
			'image_links': 'media_link',
			'notes': 'notes_to_editor',
			'tags': 'tags',
			'video_link': 'video_link',
			'state': 'video_state',
			'edit_link': 'editor_link',
			'error': 'video_errors',
			'id': 'id',
		}
		# Maps DB column names to a decode function to convert from streamlog format to internal.
		# Omitted columns act as the identity function.
		self.column_decode = {
			'event_start': parse_utc_only,
			'event_end': parse_utc_only,
			'category': lambda v: v["name"],
			'image_links': lambda v: [link.strip() for link in v.split()] if v.strip() else [],
			'state': lambda v: v.upper(),
		}
		# Maps DB column names to an encode function to convert from internal format to streamlog.
		# Omitted columns act as the identity function.
		self.column_encode = {
			'state': lambda v: v[0].upper() + v[1:].lower(), # Titlecase
		}

	def pick_worksheets(self):
		# We don't have a concept of seperate worksheets, so just use a generic name
		return "streamlog"

	def get_rows(self):
		for row in self.client.get_rows():
			yield self.parse_row(row)

	def parse_row(self, row):
		output = {}
		for column, key in self.column_map.items():
			value = row[key]
			if column in self.column_decode:
				value = self.column_decode[column](value)
			output[column] = value

		# Implicit tags
		day = dt_to_bustime(self.bustime_start, output['event_start']) // 86400
		output['tags'] += [
			output['category'],
			"Day %d" % (day + 1) if day >= 0 else "Tech Test & Preshow",
		]
		if output["poster_moment"]:
			output['tags'] += 'Poster Moment'

		return output

	def write_value(self, worksheet, row, key, value):
		if key in self.column_encode:
			value = self.column_encode[key](value)
		self.client.write_value(row["id"], key, value)

	def mark_modified(self, worksheet):
		pass # not a concept we have
