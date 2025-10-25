
import logging
import uuid

from monotonic import monotonic

import common
import common.shifts

from .middleware import Middleware


class SheetsMiddleware(Middleware):
	# How many syncs of active sheets to do before checking inactive sheets.
	# By checking inactive sheets less often, we stay within our API limits.
	# For example, 4 syncs per inactive check * 5 seconds between syncs = 20s between inactive checks
	SYNCS_PER_INACTIVE_CHECK = 4

	# How many worksheets to keep "active" based on most recent modify time
	ACTIVE_SHEET_COUNT = 2

	# Expected quota usage per 100s =
	#  (100 / RETRY_INTERVAL) * ACTIVE_SHEET_COUNT
	#  + (100 / RETRY_INTERVAL / SYNCS_PER_INACTIVE_CHECK) * (len(worksheets) - ACTIVE_SHEET_COUNT)
	# For current values, this is 100/5 * 2 + 100/5/4 * 7 = 75

	# Number of initial rows to ignore as they contain headers
	header_rows = 1

	# Maps DB column names (or general identifier, for non-DB columns) to sheet column indexes.
	# id is required.
	column_map = {
		"id": NotImplemented,
	}

	# Maps column names to a function that parses that column's value.
	# Functions take a single arg (the value to parse) and ValueError is
	# interpreted as None.
	# Columns missing from this map default to simply using the string value.
	column_parsers = {}

	# Maps column names to a function that encodes the value to a string for the spreadsheet,
	# ie. the inverse of column_parsers.
	# A column being omitted defaults to NONE_IS_EMPTY, ie. identity function for strings, "" for None.
	column_encode = {}

	def __init__(self, client, sheet_id, worksheets, allocate_ids=False):
		self.client = client
		self.sheet_id = sheet_id
		# map {worksheet: last modify time}
		self.worksheets = {w: 0 for w in worksheets}
		self.allocate_ids = allocate_ids
		# tracks when to do inactive checks
		self.sync_count = 0
		# tracks empty rows on the sheet for us to create new rows in
		self.unassigned_rows = {}

	def pick_worksheets(self):
		"""Returns a list of worksheets to check, which may not be the same every time
		for quota limit reasons."""
		if self.sync_count % self.SYNCS_PER_INACTIVE_CHECK == 0:
			# check all worksheets
			worksheets = list(self.worksheets.keys())
		else:
			# only check most recently changed worksheets
			worksheets = sorted(
				self.worksheets.keys(), key=lambda k: self.worksheets[k], reverse=True,
			)[:self.ACTIVE_SHEET_COUNT]

		self.sync_count += 1
		return worksheets

	def get_rows(self):
		"""Fetch all rows of worksheet, parsed into a list of dicts.
		Return (is_full, all rows).
		"""
		# Clear previously seen unassigned rows
		self.unassigned_rows = {}
		worksheets = self.pick_worksheets()
		all_rows = []
		for worksheet in worksheets:
			rows = self.client.get_rows(self.sheet_id, worksheet)
			for row_index, row in enumerate(rows):
				# Skip first row or rows (ie. the column titles).
				# Need to do it inside the loop and not eg. use rows[1:],
				# because then row_index won't be correct.
				if row_index < self.header_rows:
					continue
				row = self.parse_row(worksheet, row_index, row)
				if row is None:
					continue

				# Handle rows without an allocated id
				if row['id'] is None:
					# Only assign a row an id if it has a start time and a description
					if not self.row_is_non_empty(row):
						self.unassigned_rows.setdefault(worksheet, []).append(row["index"])
						continue
					# If we can't allocate ids, warn and ignore.
					if not self.allocate_ids:
						logging.warning(f"Row {worksheet!r}:{row['index']} has no valid id, skipping")
						continue
					# Otherwise, allocate id for a new row.
					row['id'] = str(uuid.uuid4())
					logging.info(f"Allocating id for row {worksheet!r}:{row['index']} = {row['id']}")
					self.write_id(row)

				all_rows.append(row)
		return worksheets, all_rows

	def row_is_non_empty(self, row):
		"""Returns True if row is considered to be non-empty and should have an id assigned."""
		raise NotImplementedError

	def write_id(self, row):
		self.client.write_value(
			self.sheet_id, row["sheet_name"],
			row["index"], self.column_map['id'],
			str(row['id']),
		)

	def parse_row(self, worksheet, row_index, row):
		"""Take a row as a sequence of columns, and return a dict {column: value}.
		May return None to skip the row (used by subclasses)."""
		row_dict = {
			"sheet_name": worksheet,
			"index": row_index,
			'_parse_errors': [],
		}
		for column, index in self.column_map.items():
			if index >= len(row):
				# Sheets omits trailing columns if they're all empty, so substitute empty string
				value = ''
			else:
				value = row[index]
			if column in self.column_parsers:
				try:
					value = self.column_parsers[column](value)
				except ValueError as e:
					value = None
					row_dict['_parse_errors'].append("Failed to parse column {}: {}".format(column, e))
			row_dict[column] = value
		return row_dict

	def write_value(self, row, key, value):
		"""Write key=value to the given row, as identified by worksheet + row dict."""
		value = self.column_encode.get(key, NONE_IS_EMPTY)(value)
		return self.client.write_value(
			self.sheet_id,
			row["sheet_name"],
			row["index"],
			self.column_map[key],
			value,
		)

	def mark_modified(self, row):
		"""Mark row as having had a change made, bumping its worksheet to the top of
		the most-recently-modified queue."""
		self.worksheets[row["sheet_name"]] = monotonic()

	def _create_row(self, worksheet, id):
		"""Because the way we get the worksheet name differs for events vs playlists,
		we have the common code here and defer extracting the worksheet and id to per-type implementations"""
		unassigned_rows = self.unassigned_rows.get(worksheet, [])
		if not unassigned_rows:
			raise Exception(f"Worksheet {worksheet} has no available space to create a new row in, or it wasn't fetched")
		index = unassigned_rows.pop(0)
		row = {
			"sheet_name": worksheet,
			"id": id,
			"index": index,
		}
		logging.info(f"Assigning existing id {row['id']} to empty row {worksheet!r}:{row['index']}")
		self.write_id(row)
		return row


# Helpers for parsing
EMPTY_IS_NONE = lambda v: None if v == "" else v
NONE_IS_EMPTY = lambda v: "" if v is None else v
PARSE_CHECKMARK = lambda v: v == "[✓]"
ENCODE_CHECKMARK = lambda v: "[✓]" if v else ""

def check_playlist(playlist_id):
	playlist_id = playlist_id.strip()
	if not playlist_id:
		return None
	if len(playlist_id) != 34 or not playlist_id.startswith('PL'):
		raise ValueError("Playlist ID appears to be invalid")
	return playlist_id


class SheetsPlaylistsMiddleware(SheetsMiddleware):
	header_rows = 2

	column_map = {
		"tags": 0,
		"description": 1,
		"name": 2,
		"playlist_id": 3,
		"show_in_description": 4,
		"default_template": 5,
		"first_event_id": 6,
		"last_event_id": 7,
		"id": 8,
	}

	column_parsers = {
		"tags": lambda v: (
			None if v.strip() == "" else
			[] if v == "<all>" else
			[tag.strip() for tag in v.split(",") if tag.strip()]
		),
		"playlist_id": check_playlist,
		"show_in_description": PARSE_CHECKMARK,
		"first_event_id": EMPTY_IS_NONE,
		"last_event_id": EMPTY_IS_NONE,
		"id": EMPTY_IS_NONE,
		"default_template": EMPTY_IS_NONE,
	}

	column_encode = {
		"tags": lambda v: (
			"" if v is None else
			"<all>" if v == [] else
			", ".join(v)
		),
		"show_in_description": ENCODE_CHECKMARK,
	}

	def parse_row(self, worksheet, row_index, row):
		row = super().parse_row(worksheet, row_index, row)
		if row["id"] == "<ignore>":
			# Special case, row is marked to be ignored
			return None
		return row

	def row_was_expected(self, db_row, worksheets):
		# Database does not record a worksheet for playlists, we assume there's only one
		# sheet and so it should always be there.
		return True

	def row_is_non_empty(self, row):
		return row["tags"] is not None or any(
			row[key] for key in ("description", "name", "playlist_id")
		)

	def create_row(self, row):
		# Always create in the first worksheet. We should only have one anyway.
		worksheet = list(self.worksheets.keys())[0]
		return self._create_row(worksheet, row.id)


class SheetsEventsMiddleware(SheetsMiddleware):
	column_map = {
		'event_start': 0,
		'event_end': 1,
		'category': 2,
		'description': 3,
		'submitter_winner': 4,
		'poster_moment': 5,
		'image_links': 6,
		'marked_for_edit': 7,
		'notes': 8,
		'tags': 9,
		'video_link': 11,
		'state': 12,
		'edit_link': 13,
		'error': 14,
		'id': 15,
	}

	def __init__(self, client, sheet_id, worksheets, bustime_start, edit_url, shifts, allocate_ids=False):
		super().__init__(client, sheet_id, worksheets, allocate_ids)
		self.bustime_start = bustime_start
		self.edit_url = edit_url
		self.shifts = shifts

		self.latest_shifts = common.shifts.parse_shifts(self.shifts)

		# column parsers are defined here so they can reference self
		self.column_parsers = {
			'event_start': self.parse_bustime,
			'event_end': lambda v: self.parse_bustime(v, preserve_dash=True),
			'poster_moment': PARSE_CHECKMARK,
			'image_links': lambda v: [link.strip() for link in v.split()] if v.strip() else [],
			'tags': lambda v: [tag.strip() for tag in v.split(',') if tag.strip()],
			'id': EMPTY_IS_NONE,
			'error': EMPTY_IS_NONE,
			'video_link': EMPTY_IS_NONE,
		}
		self.column_encode = {
			"event_start": self.encode_bustime,
			"event_end": lambda v: ("--" if v[0] else self.encode_bustime(v[1])),
			"poster_moment": ENCODE_CHECKMARK,
			"image_links": lambda v: " ".join(v),
			"tags": lambda v: ", ".join(v),
		}

	def get_rows(self):
		# only need to update the shifts once per sync
		try:
			self.latest_shifts = common.shifts.parse_shifts(self.shifts)
		except Exception:
			logging.exception('Error parsing shifts with. Using previous shifts definition.')

		return super().get_rows()

	def parse_bustime(self, value, preserve_dash=False):
		"""Convert from HH:MM or HH:MM:SS format to datetime.
		If preserve_dash=True and value is "--", returns "--"
		as a sentinel value instead of None. "" will still result in None.
		"""
		if not value.strip():
			return None
		if value.strip() == "--":
			return "--" if preserve_dash else None
		bustime = common.parse_bustime(value)
		return common.bustime_to_dt(self.bustime_start, bustime)

	def encode_bustime(self, value):
		"""Inverse of parse_bustime"""
		if value is None:
			return ""
		bustime = common.dt_to_bustime(self.bustime_start, value)
		return common.format_bustime(bustime, round="minute")

	def row_was_expected(self, db_row, worksheets):
		return db_row.sheet_name in worksheets

	def row_is_non_empty(self, row):
		return any(row[col] for col in ["event_start", "description"])

	def parse_row(self, worksheet, row_index, row):
		row_dict = super().parse_row(worksheet, row_index, row)

		# As a special case, add some implicit tags to the tags column.
		# We prepend these to make it slightly more consistent for the editor,
		# ie. it's always DAY, CATEGORY, POSTER_MOMENT, CUSTOM
		# This is only needed for full events (not the archive sheet),
		# so only do it if we had a tags column in the first place.
		if 'tags' in row_dict:
			shift_tag = common.shifts.calculate_shift(row_dict['event_start'], self.latest_shifts)
			row_dict['tags'] = (
				([shift_tag] if shift_tag is not None else [])
				+ [
					row_dict['category'], # category name
					worksheet, # sheet name
				] + (['Poster Moment'] if row_dict['poster_moment'] else [])
				+ (['rdp-troll'] if row_dict['description'].startswith('RDP Troll:') else [])
				+ row_dict['tags']
			)

		# As a special case, transform event_end into (dashed, value) form
		# where value = event_start if dashed is true.
		event_end = row_dict["event_end"]
		row_dict["event_end"] = (
			(True, row_dict["event_start"])
			if event_end == "--"
			else (False, event_end)
		)

		# Set edit link if marked for editing and start/end set.
		# This prevents accidents / clicking the wrong row and provides
		# feedback that sheet sync is still working.
		# Also clear it if it shouldn't be set.
		# We do this here instead of in sync_row() because it's Sheets-specific logic
		# that doesn't depend on the DB event in any way.
		edit_link = self.edit_url.format(row_dict['id']) if self.show_edit_url(row_dict) else ''
		if row_dict['edit_link'] != edit_link:
			logging.info("Updating sheet row {} with edit link {}".format(row_dict['id'], edit_link))
			self.write_value(row_dict, "edit_link", edit_link)
			self.mark_modified(row_dict)

		return row_dict

	def show_edit_url(self, row):
		return row['marked_for_edit'] == '[+] Marked'

	def write_value(self, row, key, value):
		# Undo the implicitly added tags
		if key == "tags":
			value = value[2:]
			if row.get("poster_moment"):
				value = value[1:]
			if row.get('rdp-troll'):
				value = value[1:]
		return super().write_value(row, key, value)

	def create_row(self, row):
		return self._create_row(row.sheet_name, row.id)


class SheetsArchiveMiddleware(SheetsEventsMiddleware):
	# Archive sheet is similar to events sheet but is missing some columns.
	header_rows = 3
	column_map = {
		'event_start': 0,
		'event_end': 1,
		'description': 2,
		'state': 3,
		'notes': 4,
		'edit_link': 6,
		'error': 7,
		'id': 8,
	}

	def show_edit_url(self, row):
		return row['event_start'] is not None and row['event_end'][1] is not None
