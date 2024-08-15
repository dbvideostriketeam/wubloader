

class Middleware:
	"""A common interface for connecting sheetsync to a "sheet" source,
	including specifics for a certain row type."""

	def get_rows(self):
		"""Fetch rows from the sheet, parsed into a list of dicts.
		The returned dicts have the following guarenteed keys:
			id: A unique identifier for the row
			sheet_name: The worksheet associated with the row.
				The concept of a worksheet is not common to all backends, but some identifying string
				is still required.
			_parse_errors: A list of error messages encountered when parsing, to be surfaced to the
				user if possible.
		In addition to the list of dicts, should return a list of worksheets fetched from,
		which is then passed to row_was_expected().
		Returns (worksheets, rows).
		"""
		raise NotImplementedError

	def row_was_expected(self, db_row, worksheets):
		"""Given a database row and list of worksheets from get_rows(), return whether
		the given row should have been present in the returned rows, ie. if we expected
		to find it on one of those worksheets."""
		# Default to the common case, which is that we always return all data
		# so the row should always be expected.
		return True

	def write_value(self, row, key, value):
		"""Write key=value to the given row. Takes the full row object so any identifying info
		can be read from it as needed."""
		raise NotImplementedError

	def mark_modified(self, row):
		"""Called if any sync action was performed due to this row.
		Intended as a way to keep track of recently-changed rows for quota optimization."""
		pass

	def create_row(self, worksheet, id):
		"""Create a new row with given id in the given worksheet and return it.
		Only used for reverse sync."""
		raise NotImplementedError
