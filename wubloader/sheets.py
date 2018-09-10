

"""The classes in the file wrap the gspread API to present a simpler interface,
which transparently handles re-connecting, sheets schemas and tracking rows by id.
"""

# schemas maps sheet name to schema.
# each schema contains a map from column names to column indexes (1-based)
SCHEMAS = {
	"heartbeat": {
		"id": 1,
		"heartbeat": 2,
	},
	"chunks": {
		# TODO
	},
	"main": {
		# TODO
	},
}


class SheetsManager(object):
	"""
	Allows each kind of named sheet to be accessed via item lookup, eg. sheets["heartbeat"].
	Sheet names given under IS_SINGLE return single sheets, others return a list of sheets.
	"""
	IS_SINGLE = ["heartbeat"]
	REFRESH_THRESHOLD = 120

	_client = None

	def __init__(self, sheet_configs, creds):
		"""
		sheet_configs should be a map from each sheet name to a tuple (if name in IN_SINGLE),
		or list of tuples (sheet_id, worksheet_title), indicating the sheet id and
		worksheet name of each worksheet to be associated with that name.

		creds should be a map containing the keys private_key and client_email,
		as required by google's auth.
		"""
		self._creds = SignedJwtAssertionCredentials(
			service_account_name=creds['client_email'],
			private_key=creds['private_key'],
			scope=['https://spreadsheets.google.com/feeds'],
		)

		# gspread library may not be threadsafe, so for safety we enclose all accesses with this lock
		self.lock = gevent.lock.RLock()

		# all client usage should be wrapped in manager.lock and begin with manager.refresh()
		self.client = gspread.authorize(self._creds)

		self.sheets = {}
		for name, config in sheet_configs.items():
			if name in self.IS_SINGLE:
				self.sheets[name] = Sheet(self, SCHEMAS[name], *config)
			else:
				self.sheets[name] = [Sheet(self, SCHEMAS[name], *c) for c in config]

	def refresh(self):
		"""Checks if client auth needs refreshing, and does so if needed."""
		if self._creds.get_access_token().expires_in < self.REFRESH_THRESHOLD:
			self._client.login() # refresh creds

	def __getitem__(self, item):
		return self.sheets[item]


class Sheet(object):
	"""Represents a single worksheet. Rows can be looked up by id by getitem: row = sheet[id].
	This will return None if the id cannot be found.
	Rows can be created by append().
	You can search through all rows by iterating over this sheet.
	"""
	def __init__(self, manager, schema, sheet_id, worksheet_title):
		self.manager = manager
		self.schema = schema
		self.sheet_id = sheet_id
		self.worksheet_title = worksheet_title
		self.worksheet = self.manager.client.open_by_key(sheet_id).worksheet(worksheet_title)

	def __repr__(self):
		return "<{cls.__name__} {self.sheet_id!r}/{self.worksheet_title!r} at {id:x}>".format(cls=type(self), self=self, id=id(self))
	__str__ = __repr__

	def __getitem__(self, item):
		return self.find_row(item)

	def __iter__(self):
		with self.manager.lock:
			self.manager.refresh()
			return [Row(self, schema, i+1, r) for i, r in enumerate(self.worksheet.get_all_values())]

	def find_row(self, id):
		for row in self:
			if row.id == id:
				return row
		return None

	def by_index(self, index):
		with self.manager.lock:
			self.manager.refresh()
			return Row(self, schema, index, self.worksheet.row_values(index))

	def append(self, id, **values):
		"""Create new row with given initial values, and return it."""
		values['id'] = id
		rendered = ["" for _ in range(max(self.schema.values()))]
		for name, value in values.items():
			rendered[self.schema[name]-1] = value
		with self.manager.lock:
			self.manager.refresh()
			self.worksheet.append_row(rendered)
			row = self[id]
			if not row:
				raise Exception("Unrecoverable race condition: Created new row with id {} but then couldn't find it".format(id))
			return row


class Row(object):
	"""Represents a row in a sheet. Values can be looked up by attribute.
	Values can be updated with update(attr=value), which returns the updated row.
	Note that a row must have an id to be updatable. Updating is permitted if no id is set
	only if id is one of the values being written.
	You can also refresh the row (if it has an id) by calling row.refresh(),
	which returns the newly read row, or None if it can no longer be found.
	"""

	def __init__(self, sheet, schema, index, values):
		self.sheet = sheet
		self.manager = sheet.manager
		self.schema = schema
		self.index = index
		self.values = values

	def __repr__(self):
		return "<{cls.__name__} {self.id}({self.index}) of {self.sheet} at {id:x}>".format(cls=type(self), self=self, id=id(self))
	__str__ = __repr__

	def __getattr__(self, attr):
		col = self.schema[attr]
		if len(self.values) > col:
			return self.values[col]
		return ""

	def update(self, **values):
		with self.manager.lock:
			self.manager.refresh()
			# We attempt to detect races by:
			#  Always refreshing our position before we begin (if we can)
			#  Checking our position again afterwards. If it's changed, we probably mis-wrote.
			if self.id:
				before = self.refresh()
			else:
				before = self
			for name, value in values.items():
				col = self.schema[name]
				self.sheet.worksheet.update_cell(before.index, col, value)
			after = self.sheet.by_index(before.index)
			new_id = values['id'] if 'id' in values else self.id
			if after.id != new_id:
				raise Exception("Likely bad write: Row {} may have had row {} data partially written: {}".format(after, before, values))

	def refresh(self):
		return self.sheet[self.id]
