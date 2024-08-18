
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

	def get_entries(self):
		"""Return a list of log entries, where each row is a dict"""
		return self.request("GET", "event", self.event_id, "log")

	def get_tags(self):
		"""Return a list of dicts representing tags objects"""
		return self.request("GET", "event", self.event_id, "tags")

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


class StreamLogPlaylistsMiddleware(Middleware):
	# There's no point sharing any code with StreamLogEventsMiddleware,
	# the operations are too different.
	def __init__(self, client, playlists_worksheet):
		self.client = client
		self.playlists_worksheet = playlists_worksheet

	def get_rows(self):
		rows = []
		for tag in self.client.get_tags():
			row = {
				"id": tag["id"],
				"sheet_name": self.playlists_worksheet,
				"_parse_errors": [],
				# Special case for the "all everything" list, otherwise all playlists have a single tag.
				"tags": [] if tag["tag"] == "<all>" else [tag["tag"]],
				"description": tag["description"],
				"playlist_id": None,
				"name": "",
				"show_in_description": False,
				"first_event_id": None, # TODO missing in StreamLog
				"last_event_id": None, # TODO missing in StreamLog
			}
			playlist = tag["playlist"]
			if playlist is not None:
				row["playlist_id"] = playlist["id"]
				row["name"] = playlist["title"]
				row["show_in_description"] = playlist["shows_in_video_descriptions"]
			rows.append(row)
		return None, rows

	# writing intentionally not implemented


class StreamLogEventsMiddleware(Middleware):
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
			'state': 'video_processing_state',
			'error': 'video_errors',
			'id': 'id',
		}
		# Maps DB column names to a decode function to convert from streamlog format to internal.
		# Omitted columns act as the identity function.
		self.column_decode = {
			'event_start': parse_utc_only,
			'event_end': lambda v: parse_utc_only(v["time"]) if v["type"] == "Time" else None,
			'category': lambda v: v["name"],
			'state': lambda v: v.upper() if v else None,
			'error': lambda v: None if v == '' else v,
			'tags': lambda v: [tag["tag"] for tag in v],
		}
		# Maps DB column names to an encode function to convert from internal format to streamlog.
		# Omitted columns act as the identity function.
		self.column_encode = {
			'state': lambda v: v[0].upper() + v[1:].lower() if v else None, # Titlecase
			'error': lambda v: '' if v == None else v,
		}
		# Maps DB column names to the url part you need to write to to set it.
		self.write_map = {
			"state": "video_processing_state",
			"error": "video_errors",
			"video_link": "video",
		}

	def get_rows(self):
		all_rows = []
		for row in self.client.get_entries()["event_log"]:
			row = self.parse_row(row)
			# Malformed rows can be skipped, represented as a None result
			if row is not None:
				all_rows.append(row)
		# There's no worksheet concept here so just return None for worksheets.
		return None, all_rows

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
		output['tags'] = [
			output['category'],
			output["sheet_name"],
		] + output['tags']
		if output["poster_moment"]:
			output['tags'] += 'Poster Moment'

		return output

	def write_value(self, row, key, value):
		if key in self.column_encode:
			value = self.column_encode[key](value)
		self.client.write_value(row["id"], self.write_map[key], value)
