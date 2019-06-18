
import json
import logging
import signal
import uuid

import argh
import gevent.backdoor
import gevent.event
import prometheus_client as prom
from psycopg2 import sql
from psycopg2.extras import register_uuid

import common
import common.dateutil
from common.database import DBManager, query

from .sheets import Sheets


class SheetSync(object):

	# Time between syncs
	RETRY_INTERVAL = 5
	# Time to wait after getting an error
	ERROR_RETRY_INTERVAL = 10

	def __init__(self, stop, dbmanager, sheets, sheet_id, worksheets, edit_url, bustime_start, allocate_ids=False):
		self.stop = stop
		self.conn = dbmanager.get_conn()
		self.sheets = sheets
		self.sheet_id = sheet_id
		self.worksheets = worksheets
		self.edit_url = edit_url
		self.bustime_start = bustime_start
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
			'video_link': 10,
			'state': 11,
			'edit_link': 12,
			'error': 13,
			'id': 14,
		}
		# Maps column names to a function that parses that column's value.
		# Functions take a single arg (the value to parse) and ValueError is
		# interpreted as None.
		# Columns missing from this map default to simply using the string value.
		self.column_parsers = {
			'event_start': self.parse_bustime,
			'event_end': self.parse_bustime,
			'poster_moment': lambda v: v == u'[\u2713]', # check mark
			'image_links': lambda v: [link.strip() for link in v.split()] if v.strip() else [],
			'id': lambda v: uuid.UUID(v) if v.strip() else None,
		}
		# List of input columns
		self.input_columns = [
			'event_start',
			'event_end',
			'category',
			'description',
			'submitter_winner',
			'poster_moment',
			'image_links',
			'notes',
		]
		# List of output columns
		self.output_columns = [
			'video_link',
			'state',
			'error',
		]

	def parse_bustime(self, value):
		"""Convert from HH:MM or HH:MM:SS format to datetime"""
		bustime = common.parse_bustime(value)
		return common.bustime_to_dt(self.bustime_start, bustime)

	def wait(self, interval):
		self.stop.wait(common.jitter(interval))

	def run(self):
		while not self.stop.is_set():
			
			try:
				# Since the full dataset is small, the cost of round tripping to the database to check
				# each row is more expensive than the cost of just grabbing the entire table
				# and comparing locally.
				events = self.get_events()
				for worksheet in self.worksheets:
					rows = self.sheets.get_rows(self.sheet_id, worksheet)
					for row_index, row in enumerate(rows):
						# Skip first row. Need to do it inside the loop and not eg. use rows[1:],
						# because then row_index won't be correct.
						if row_index == 0:
							continue
						row = self.parse_row(row)
						if row['id'] is None:
							if self.allocate_ids:
								row['id'] = uuid.uuid4()
								logging.info("Allocating id for row {!r}:{} = {}".format(worksheet, row_index, row['id']))
								self.sheets.write_value(
									self.sheet_id, worksheet,
									row_index, self.column_map['id'],
									str(row['id']),
								)
							else:
								logging.warning("Row {!r}:{} has no valid id, skipping".format(worksheet, row_index))
								continue
						self.sync_row(worksheet, row_index, row, events.get(row['id']))
			except Exception:
				logging.exception("Failed to sync")
				self.wait(self.ERROR_RETRY_INTERVAL)
			else:
				logging.info("Successful sync")
				self.wait(self.RETRY_INTERVAL)

	def get_events(self):
		"""Return the entire events table as a map {id: event namedtuple}"""
		result = query(self.conn, "SELECT * FROM events")
		by_id = {}
		for row in result.fetchall():
			by_id[row.id] = row
		return by_id

	def parse_row(self, row):
		"""Take a row as a sequence of columns, and return a dict {column: value}"""
		row_dict = {}
		for column, index in self.column_map.items():
			if index >= len(row):
				# Sheets omits trailing columns if they're all empty, so substitute empty string
				value = ''
			else:
				value = row[index]
			if column in self.column_parsers:
				try:
					value = self.column_parsers[column](value)
				except ValueError:
					value = None
			row_dict[column] = value
		return row_dict

	def sync_row(self, worksheet, row_index, row, event):
		"""Take a row dict and an Event from the database (or None if id not found)
		and take whatever action is required to sync them, ie. writing to the database or sheet."""

		if event is None:
			# No event currently in DB, if any field is non-empty, then create it.
			# Otherwise ignore it.
			if not any(row[col] for col in self.input_columns):
				return
			logging.info("Inserting new event {}".format(row['id']))
			# Insertion conflict just means that another sheet sync beat us to the insert.
			# We can ignore it.
			insert_cols = ['id'] + self.input_columns
			built_query = sql.SQL("""
				INSERT INTO events ({})
				VALUES ({})
				ON CONFLICT DO NOTHING
			""").format(
				sql.SQL(", ").join(sql.Identifier(col) for col in insert_cols),
				sql.SQL(", ").join(sql.Placeholder(col) for col in insert_cols),
			)
			query(self.conn, built_query, **row)
			return

		# Update database with any changed inputs
		changed = [col for col in self.input_columns if row[col] != getattr(event, col)]
		if changed:
			logging.info("Updating event {} with new value(s) for {}".format(
				row['id'], ', '.join(changed)
			))
			built_query = sql.SQL("""
				UPDATE events
				SET {}
				WHERE id = %(id)s
			""").format(sql.SQL(", ").join(
				sql.SQL("{} = {}").format(
					sql.Identifier(col), sql.Placeholder(col)
				) for col in changed
			))
			query(self.conn, built_query, **row)

		# Update sheet with any changed outputs
		format_output = lambda v: '' if v is None else v # cast nulls to empty string
		changed = [col for col in self.output_columns if row[col] != format_output(getattr(event, col))]
		if changed:
			logging.info("Updating sheet row {} with new value(s) for {}".format(
				row['id'], ', '.join(changed)
			))
			for col in changed:
				self.sheets.write_value(
					self.sheet_id, worksheet,
					row_index, self.column_map[col],
					format_output(getattr(event, col)),
				)

		# Set edit link if marked for editing and start/end set.
		# This prevents accidents / clicking the wrong row and provides
		# feedback that sheet sync is still working.
		# Also clear it if it shouldn't be set.
		edit_link = self.edit_url.format(row['id']) if row['marked_for_edit'] == '[+] Marked' else ''
		if row['edit_link'] != edit_link:
			logging.info("Updating sheet row {} with edit link {}".format(row['id'], edit_link))
			self.sheets.write_value(
				self.sheet_id, worksheet,
				row_index, self.column_map['edit_link'],
				edit_link,
			)


@argh.arg('worksheet-names', nargs='+', help="The names of the individual worksheets within the sheet to operate on.")
def main(dbconnect, sheets_creds_file, edit_url, bustime_start, sheet_id, worksheet_names, metrics_port=8004, backdoor_port=0, allocate_ids=False):
	"""dbconnect should be a postgres connection string, which is either a space-separated
	list of key=value pairs, or a URI like:
		postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE

	sheets_creds_file should be a json file containing keys 'client_id', 'client_secret' and 'refresh_token'.

	edit_url should be a format string for edit links, with {} as a placeholder for id.
	eg. "https://myeditor.example.com/edit/{}" will produce edit urls like
	"https://myeditor.example.com/edit/da6cf4df-4871-4a9a-a660-0b1e1a6a9c10".

	bustime_start is the timestamp which is bustime 00:00.

	--allocate-ids means that it will give rows without ids an id.
	Only one sheet sync should have --allocate-ids on for a given sheet at once!
	"""
	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	register_uuid()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	stop = gevent.event.Event()
	gevent.signal(signal.SIGTERM, stop.set) # shut down on sigterm

	bustime_start = common.dateutil.parse(bustime_start)

	logging.info("Starting up")

	dbmanager = DBManager(dsn=dbconnect)
	sheets_creds = json.load(open(sheets_creds_file))

	sheets = Sheets(
        client_id=sheets_creds['client_id'],
        client_secret=sheets_creds['client_secret'],
        refresh_token=sheets_creds['refresh_token'],
	)

	SheetSync(stop, dbmanager, sheets, sheet_id, worksheet_names, edit_url, bustime_start, allocate_ids).run()

	logging.info("Gracefully stopped")
