"""The classes in the file wrap the gspread API to present a simpler interface,
which transparently handles re-connecting, sheets schemas and tracking rows by id.
"""

import random
import string

import gevent.lock

from oauth2client.client import SignedJwtAssertionCredentials
import gspread

from . import states


# schemas maps sheet name to schema.
# each schema contains a map from column names to column indexes (1-based)
SCHEMAS = {
	"heartbeat": {
		"id": 1,
		"heartbeat": 2,
	},
	"chunks": {
		"start": 1,
		"end": 2,
		"description": 4,
		"link": 5,
		"state": 6,
		"uploader": 7,
		"notes": 8,
		"id": 9,
		"cut_time": 10,
		"upload_time": 11,
		"duration": 12,
	},
	"main": {
		"start": 1,
		"end": 2,
		"description": 4,
		"link": 7,
		"state": 8,
		"location": 9,
		"uploader": 10,
		"notes": 12,
		"id": 14,
		"draft_time": 15,
		"cut_time": 16,
		"upload_time": 17,
		"duration": 18,
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
			return [Row(self, self.schema, i+1, r) for i, r in enumerate(self.worksheet.get_all_values())]

	def find_row(self, id):
		for row in self:
			if row.id == id:
				return row
		return None

	def by_index(self, index):
		with self.manager.lock:
			self.manager.refresh()
			return Row(self, self.schema, index, self.worksheet.row_values(index))

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
	If a row without an id is updated, an id will be randomly assigned.
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

	def _raw_update(self, name, value):
		col = self.schema[name]
		self.sheet.worksheet.update_cell(self.index, col, value)

	def update(self, **values):
		with self.manager.lock:
			self.manager.refresh()
			while True:
				# We attempt to detect races by:
				#  Always refreshing our position before we begin (if we can)
				#  Checking our position again afterwards. If it's changed, we probably mis-wrote.
				if self.id:
					before = self.refresh()
					if before is None:
						raise Exception("Cannot update row {}: Row is gone".format(self))
				else:
					before = self
					if 'id' not in values:
						# auto-create id
						values['id'] = ''.join(random.choice(string.letters + string.digits) for _ in range(12))
				for name, value in values.items():
					before._raw_update(name, value)
				after = self.sheet.by_index(before.index)
				new_id = values['id'] if 'id' in values else self.id
				if after.id != new_id:
					logging.error("Likely bad write: Row {} may have had row {} data partially written: {}".format(after, before, values))
					if hasattr(after, 'state'):
						after._raw_update('state', states.ERROR)
					if hasattr(after, 'notes'):
						after._raw_update('notes', "This row may have had following data from row with id {} written to it: {}".format(new_id, values))
					continue # retry
				return

	def refresh(self):
		return self.sheet[self.id]
