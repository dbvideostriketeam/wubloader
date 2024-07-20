
import logging

from .googleapis import GoogleAPIClient


class Sheets(object):
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
