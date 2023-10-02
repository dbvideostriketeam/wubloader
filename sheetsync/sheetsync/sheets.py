
import logging
import uuid

from monotonic import monotonic

import common
from common.googleapis import GoogleAPIClient


class SheetsClient(object):
	"""Manages Google Sheets API operations"""

	def __init__(self, client_id, client_secret, refresh_token):
		self.logger = logging.getLogger(type(self).__name__)
		self.client = GoogleAPIClient(client_id, client_secret, refresh_token)

	def get_rows(self, spreadsheet_id, sheet_name, range=None):
		"""Return a list of rows, where each row is a list of the values of each column.
		Range optionally restricts returned rows, and uses A1 format, eg. "A1:B5".
		"""
		if range:
			range = "'{}'!{}".format(sheet_name, range)
		else:
			range = "'{}'".format(sheet_name)
		resp = self.client.request('GET',
			'https://sheets.googleapis.com/v4/spreadsheets/{}/values/{}'.format(
				spreadsheet_id, range,
			),
			metric_name='get_rows',
		)
		resp.raise_for_status()
		data = resp.json()
		return data['values']

	def write_value(self, spreadsheet_id, sheet_name, row, column, value):
		"""Write value to the row and column (0-based) given."""
		range = "'{sheet}'!{col}{row}:{col}{row}".format(
			sheet = sheet_name,
			row = row + 1, # 1-indexed rows in range syntax
			col = self.index_to_column(column),
		)
		resp = self.client.request('PUT',
			'https://sheets.googleapis.com/v4/spreadsheets/{}/values/{}'.format(
				spreadsheet_id, range,
			),
			params={
				"valueInputOption": "1", # RAW
			},
			json={
				"range": range,
				"values": [[value]],
			},
			metric_name='write_value',
		)
		resp.raise_for_status()

	def index_to_column(self, index):
		"""For a given column index, convert to a column description, eg. 0 -> A, 1 -> B, 26 -> AA."""
		# This is equivalent to the 0-based index in base-26 (where A = 0, B = 1, ..., Z = 25)
		digits = []
		while index:
			index, digit = divmod(index, 26)
			digits.append(digit)
		# We now have the digits, but they're backwards.
		digits = digits[::-1]
		# Now convert the digits to letters
		digits = [chr(ord('A') + digit) for digit in digits]
		# Finally, convert to string
		return ''.join(digits)


class SheetsMiddleware():
	# How many syncs of active sheets to do before checking inactive sheets.
	# By checking inactive sheets less often, we stay within our API limits.
	# For example, 4 syncs per inactive check * 5 seconds between syncs = 20s between inactive checks
	SYNCS_PER_INACTIVE_CHECK = 4

	# How many worksheets to keep "active" based on most recent modify time
	ACTIVE_SHEET_COUNT = 2

	# Expected quota usage per 100s =
	#  (100 / RETRY_INTERVAL) * ACTIVE_SHEET_COUNT
	#  + (100 / RETRY_INTERVAL / SYNCS_PER_INACTIVE_CHECK) * (len(worksheets) - ACTIVE_SHEET_COUNT)
	# If playlist_worksheet is defined, add 1 to len(worksheets).
	# For current values, this is 100/5 * 2 + 100/5/4 * 7 = 75

	def __init__(self, client, sheet_id, worksheets, bustime_start, edit_url, allocate_ids=False):
		self.client = client
		self.sheet_id = sheet_id
		# map {worksheet: last modify time}
		self.worksheets = {w: 0 for w in worksheets}
		self.edit_url = edit_url
		self.allocate_ids = allocate_ids
		# Maps DB column names (or general identifier, for non-DB columns) to sheet column indexes.
		# Hard-coded for now, future work: determine this from column headers in sheet
		self.column_map = {
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
		# Maps column names to a function that parses that column's value.
		# Functions take a single arg (the value to parse) and ValueError is
		# interpreted as None.
		# Columns missing from this map default to simply using the string value.
		self.column_parsers = {
			'event_start': lambda v: self.parse_bustime(v),
			'event_end': lambda v: self.parse_bustime(v, preserve_dash=True),
			'poster_moment': lambda v: v == '[\u2713]', # check mark
			'image_links': lambda v: [link.strip() for link in v.split()] if v.strip() else [],
			'tags': lambda v: [tag.strip() for tag in v.split(',') if tag.strip()],
			'id': lambda v: v if v.strip() else None,
		}
		# tracks when to do inactive checks
		self.sync_count = 0

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

	def pick_worksheets(self):
		"""Returns a list of worksheets to check, which may not be the same every time
		for quota limit reasons."""
		if self.sync_count % self.SYNCS_PER_INACTIVE_CHECK == 0:
			# check all worksheets
			worksheets = self.worksheets
		else:
			# only check most recently changed worksheets
			worksheets = sorted(
				self.worksheets.keys(), key=lambda k: self.worksheets[k], reverse=True,
			)[:self.ACTIVE_SHEET_COUNT]

		self.sync_count += 1
		return worksheets

	def get_rows(self, worksheet):
		"""Fetch all rows of worksheet, parsed into a list of dicts."""
		rows = self.sheets.get_rows(self.sheet_id, worksheet)
		for row_index, row in enumerate(rows):
			# Skip first row (ie. the column titles).
			# Need to do it inside the loop and not eg. use rows[1:],
			# because then row_index won't be correct.
			if row_index == 0:
				continue
			row = self.parse_row(worksheet, row_index, row)

			# Handle rows without an allocated id
			if row['id'] is None:
				# If a row is all empty (including no id), ignore it.
				# Ignore the tags column for this check since it is never non-empty due to implicit tags
				# (and even if there's other tags, we don't care if there's nothing else in the row).
				if not any(row[col] for col in self.input_columns if col != 'tags'):
					continue
				# If we can't allocate ids, warn and ignore.
				if not self.allocate_ids:
					logging.warning(f"Row {worksheet!r}:{row['index']} has no valid id, skipping")
					continue
				# Otherwise, allocate id for a new row.
				row['id'] = str(uuid.uuid4())
				logging.info(f"Allocating id for row {worksheet!r}:{row['index']} = {row['id']}")
				self.sheets.write_value(
					self.sheet_id, worksheet,
					row["index"], self.column_map['id'],
					str(row['id']),
				)

			# Set edit link if marked for editing and start/end set.
			# This prevents accidents / clicking the wrong row and provides
			# feedback that sheet sync is still working.
			# Also clear it if it shouldn't be set.
			# We do this here instead of in sync_row() because it's Sheets-specific logic
			# that doesn't depend on the DB event in any way.
			edit_link = self.edit_url.format(row['id']) if row['marked_for_edit'] == '[+] Marked' else ''
			if row['edit_link'] != edit_link:
				logging.info("Updating sheet row {} with edit link {}".format(row['id'], edit_link))
				self.write_value(row, "edit_link", edit_link)
				self.mark_modified(row)

			yield row

	def parse_row(self, worksheet, row_index, row):
		"""Take a row as a sequence of columns, and return a dict {column: value}"""
		row_dict = {'_parse_errors': []}
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
		# As a special case, add some implicit tags to the tags column.
		# We prepend these to make it slightly more consistent for the editor,
		# ie. it's always DAY, CATEGORY, POSTER_MOMENT, CUSTOM
		row_dict['tags'] = (
			[
				row_dict['category'], # category name
				worksheet, # sheet name
			] + (['Poster Moment'] if row_dict['poster_moment'] else [])
			+ row_dict['tags']
		)
		# As a special case, treat an end time of "--" as equal to the start time.
		if row_dict["event_end"] == "--":
			row_dict["event_end"] = row_dict["event_start"]
		# Always include row index and worksheet
		row_dict["index"] = row_index
		row_dict["sheet_name"] = worksheet
		return row_dict

	def write_value(self, row, key, value):
		"""Write key=value to the given row, as identified by worksheet + row dict."""
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
