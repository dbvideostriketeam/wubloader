

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
		In addition to the list of dicts, should return an "is_full" boolean which is True
		if all rows were fetched or False if only some subset was fetched (eg. for quota management reasons).
		Returns (is_full, rows).
		"""
		raise NotImplementedError

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
