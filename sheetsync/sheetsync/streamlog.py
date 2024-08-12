
import json
import logging

import requests

from common.dateutil import parse_utc_only

from .middleware import Middleware


class StreamLogClient():
	"""Client for Stream Log server"""

	def __init__(self, url, event_id, auth_token):
		self.url = url
		self.auth_token = auth_token
		self.event_id = event_id
		self.session = requests.Session()

	def get_rows(self):
		"""Return a list of rows, where each row is a dict"""
		return self.request("GET", "event", self.event_id, "log")

	def write_value(self, row_id, key, value):
		"""Write key=value for the given row, or delete if value=None"""
		logging.debug("Write to streamlog {} {} = {!r}".format(row_id, key, value))
		if value is None:
			return self.request("DELETE", "entry", row_id, key)
		else:
			return self.request("POST", "entry", row_id, key, body=value)

	def request(self, method, *path, body=None):
		response = self.session.request(method, "/".join((self.url, "api", "v1") + path),
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


class StreamLogMiddleware(Middleware):
	def __init__(self, client):
		self.client = client
		# Maps DB column names to streamlog fields.
		self.column_map = {
			'event_start': 'start_time',
			'event_end': 'end_time',
			'category': 'entry_type',
			'description': 'description',
			'submitter_winner': 'submitter_or_winner',
			'poster_moment': 'poster_moment',
			'image_links': 'media_links',
			'notes': 'notes_to_editor',
			'tags': 'tags',
			'video_link': 'video_link',
			'state': 'video_state',
			'error': 'video_errors',
			'id': 'id',
		}
		# Maps DB column names to a decode function to convert from streamlog format to internal.
		# Omitted columns act as the identity function.
		self.column_decode = {
			'event_start': parse_utc_only,
			'event_end': lambda v: parse_utc_only(v["time"]) if v["type"] == "Time" else None,
			'category': lambda v: v["name"],
			'state': lambda v: None if v is None else v.upper(),
			'error': lambda v: None if v == '' else v,
		}
		# Maps DB column names to an encode function to convert from internal format to streamlog.
		# Omitted columns act as the identity function.
		self.column_encode = {
			'state': lambda v: v[0].upper() + v[1:].lower(), # Titlecase
			'error': lambda v: '' if v == None else v,
		}
		# Maps DB column names to the url part you need to write to to set it.
		self.write_map = {
			"state": "video_state",
			"error": "video_errors",
			"video_link": "video",
		}

	def get_rows(self):
		all_rows = []
		for row in self.client.get_rows()["event_log"]:
			row = self.parse_row(row)
			# Malformed rows can be skipped, represented as a None result
			if row is not None:
				all_rows.append(row)
		# There's no worksheet concept here so we always return a full sync.
		return True, all_rows

	def parse_row(self, row):
		output = {}
		for column, key in self.column_map.items():
			value = row[key]
			if column in self.column_decode:
				try:
					value = self.column_decode[column](value)
				except Exception:
					logging.exception(f"Failed to parse {key} value {value!r} of row {row['id']}, skipping")
					return
			output[column] = value

		# Tab name is sheet name
		output["sheet_name"] = row["tab"]["name"] if row["tab"] else "unknown"

		# Implicit tags
		output['tags'] += [
			output['category'],
			output["sheet_name"],
		]
		if output["poster_moment"]:
			output['tags'] += 'Poster Moment'

		return output

	def write_value(self, row, key, value):
		if key in self.column_encode:
			value = self.column_encode[key](value)
		self.client.write_value(row["id"], self.write_map[key], value)
