
import json
import logging
import signal
import uuid
from collections import defaultdict

import argh
import gevent.backdoor
import gevent.event
import prometheus_client as prom
from monotonic import monotonic
from psycopg2 import sql
from psycopg2.extras import register_uuid
from requests import HTTPError

import common
import common.dateutil
from common.database import DBManager, query

from .sheets import Sheets

sheets_synced = prom.Counter(
	'sheets_synced',
	'Number of successful sheet syncs',
)

sync_errors = prom.Counter(
	'sync_errors',
	'Number of errors syncing sheets',
)

rows_found = prom.Counter(
	'rows_found',
	'Number of rows that sheetsync looked at with an id',
	['worksheet'],
)

rows_changed = prom.Counter(
	'rows_changed',
	'Number of rows that needed changes applied, with type=insert, type=input or type=output',
	['type', 'worksheet'],
)

event_counts = prom.Gauge(
	'event_counts',
	'Number of rows in the database',
	['sheet_name', 'category', 'poster_moment', 'state', 'errored'],
)

class SheetSync(object):

	# Time between syncs
	RETRY_INTERVAL = 5

	# Time to wait after getting an error
	ERROR_RETRY_INTERVAL = 10

	# How many syncs of active sheets to do before checking inactive sheets.
	# By checking inactive sheets less often, we stay within our API limits.
	# For example, 4 syncs per inactive check * 5 seconds between syncs = 20s between inactive checks
	SYNCS_PER_INACTIVE_CHECK = 4

	# How many worksheets to keep "active" based on most recent modify time
	ACTIVE_SHEET_COUNT = 2

	# Expected quota usage per 100s =
	#  (100 / RETRY_INTERVAL) * ACTIVE_SHEET_COUNT
	#  + (100 / RETRY_INTERVAL / SYNCS_PER_INACTIVE_CHECK) * (len(worksheets) - ACTIVE_SHEET_COUNT)
	# For current values, this is 100/5 * 2 + 100/5/4 * 6 = 70

	def __init__(self, stop, dbmanager, sheets, sheet_id, worksheets, edit_url, bustime_start, allocate_ids=False):
		self.stop = stop
		self.dbmanager = dbmanager
		self.sheets = sheets
		self.sheet_id = sheet_id
		# map {worksheet: last modify time}
		self.worksheets = {w: 0 for w in worksheets}
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
		if value.strip() in ('--', ''):
			return None
		bustime = common.parse_bustime(value)
		return common.bustime_to_dt(self.bustime_start, bustime)

	def wait(self, base, interval):
		"""Wait until INTERVAL seconds after BASE."""
		now = monotonic()
		to_wait = base + common.jitter(interval) - now
		if to_wait > 0:
			self.stop.wait(to_wait)

	def run(self):
		self.conn = self.dbmanager.get_conn()

		# tracks when to do inactive checks
		sync_count = 0

		while not self.stop.is_set():

			try:
				# Since the full dataset is small, the cost of round tripping to the database to check
				# each row is more expensive than the cost of just grabbing the entire table
				# and comparing locally.
				events = self.get_events()
				if sync_count % self.SYNCS_PER_INACTIVE_CHECK == 0:
					# check all worksheets
					worksheets = self.worksheets
				else:
					# only check most recently changed worksheets
					worksheets = sorted(
						self.worksheets.keys(), key=lambda k: self.worksheets[k], reverse=True,
					)[:self.ACTIVE_SHEET_COUNT]

				sync_count += 1
				sync_start = monotonic()

				for worksheet in worksheets:
					rows = self.sheets.get_rows(self.sheet_id, worksheet)
					for row_index, row in enumerate(rows):
						# Skip first row (ie. the column titles).
						# Need to do it inside the loop and not eg. use rows[1:],
						# because then row_index won't be correct.
						if row_index == 0:
							continue
						row = self.parse_row(row)
						self.sync_row(worksheet, row_index, row, events.get(row['id']))
			except Exception as e:
				# for HTTPErrors, http response body includes the more detailed error
				detail = ''
				if isinstance(e, HTTPError):
					detail = ": {}".format(e.response.content)
				logging.exception("Failed to sync{}".format(detail))
				sync_errors.inc()
				# To ensure a fresh slate and clear any DB-related errors, get a new conn on error.
				# This is heavy-handed but simple and effective.
				# If we can't re-connect, the program will crash from here,
				# then restart and wait until it can connect again.
				self.conn = self.dbmanager.get_conn()
				self.wait(sync_start, self.ERROR_RETRY_INTERVAL)
			else:
				logging.info("Successful sync of worksheets: {}".format(", ".join(worksheets)))
				sheets_synced.inc()
				self.wait(sync_start, self.RETRY_INTERVAL)

	def get_events(self):
		"""Return the entire events table as a map {id: event namedtuple}"""
		result = query(self.conn, "SELECT * FROM events")
		by_id = {}
		counts = defaultdict(lambda: 0)
		for row in result.fetchall():
			by_id[row.id] = row
			counts[row.sheet_name, row.category, str(row.poster_moment), row.state, str(bool(row.error))] += 1
		# Reach into metric internals and forget about all previous values,
		# or else any values we don't update will remain as a stale count.
		event_counts._metrics.clear()
		for labels, count in counts.items():
			event_counts.labels(*labels).set(count)
		return by_id

	def parse_row(self, row):
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
		return row_dict

	def sync_row(self, worksheet, row_index, row, event):
		"""Take a row dict and an Event from the database (or None if id not found)
		and take whatever action is required to sync them, ie. writing to the database or sheet."""

		if event is None:
			# No event currently in DB, if any field is non-empty, then create it.
			# Otherwise ignore it.
			if not any(row[col] for col in self.input_columns):
				return

			# Only generate row when needed (unless it's already there)
			# Originally we would allocate rows on first sync, but this led to rate limiting issues.
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
					return

			logging.info("Inserting new event {}".format(row['id']))
			# Insertion conflict just means that another sheet sync beat us to the insert.
			# We can ignore it.
			insert_cols = ['id', 'sheet_name'] + self.input_columns
			built_query = sql.SQL("""
				INSERT INTO events ({})
				VALUES ({})
				ON CONFLICT DO NOTHING
			""").format(
				sql.SQL(", ").join(sql.Identifier(col) for col in insert_cols),
				sql.SQL(", ").join(sql.Placeholder(col) for col in insert_cols),
			)
			query(self.conn, built_query, sheet_name=worksheet, **row)
			rows_found.labels(worksheet).inc()
			rows_changed.labels('insert', worksheet).inc()
			self.mark_modified(worksheet)
			return

		rows_found.labels(worksheet).inc()

		# If no database error, but we have parse errors, indicate they should be displayed.
		if event.error is None and row['_parse_errors']:
			event = event._replace(error=", ".join(row['_parse_errors']))

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
			rows_changed.labels('input', worksheet).inc()
			self.mark_modified(worksheet)

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
			rows_changed.labels('output', worksheet).inc()
			self.mark_modified(worksheet)

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
			self.mark_modified(worksheet)

	def mark_modified(self, worksheet):
		"""Mark worksheet as having had a change made, bumping it to the top of
		the most-recently-modified queue."""
		self.worksheets[worksheet] = monotonic()


@argh.arg('dbconnect', help=
	"dbconnect should be a postgres connection string, which is either a space-separated "
	"list of key=value pairs, or a URI like:\n"
	"\tpostgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE"
)
@argh.arg('sheets-creds-file', help=
	"sheets_creds_file should be a json file containing keys "
	"'client_id', 'client_secret' and 'refresh_token'."
)
@argh.arg('edit-url', help=
	'edit_url should be a format string for edit links, with {} as a placeholder for id. '
	'eg. "https://myeditor.example.com/edit/{}" will produce edit urls like '
	'"https://myeditor.example.com/edit/da6cf4df-4871-4a9a-a660-0b1e1a6a9c10".'
)
@argh.arg('bustime_start', type=common.dateutil.parse, help=
	"bustime_start is the timestamp which is bustime 00:00."
)
@argh.arg('worksheet-names', nargs='+', help=
	"The names of the individual worksheets within the sheet to operate on."
)
@argh.arg('--allocate-ids', help=
	"--allocate-ids means that it will give rows without ids an id. "
	"Only one sheet sync should have --allocate-ids on for a given sheet at once!"
)
def main(dbconnect, sheets_creds_file, edit_url, bustime_start, sheet_id, worksheet_names, metrics_port=8005, backdoor_port=0, allocate_ids=False):
	"""
	Sheet sync constantly scans a Google Sheets sheet and a database, copying inputs from the sheet
	to the DB and outputs from the DB to the sheet.

	With the exception of id allocation, all operations are idempotent and multiple sheet syncs
	may be run for redundancy.
	"""
	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	register_uuid()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	stop = gevent.event.Event()
	gevent.signal(signal.SIGTERM, stop.set) # shut down on sigterm

	logging.info("Starting up")

	dbmanager = DBManager(dsn=dbconnect)
	while True:
		try:
			# Get a test connection so we know the database is up,
			# this produces a clearer error in cases where there's a connection problem.
			conn = dbmanager.get_conn()
		except Exception:
			delay = common.jitter(10)
			logging.info('Cannot connect to database. Retrying in {:.0f} s'.format(delay))
			stop.wait(delay)
		else:
			# put it back so it gets reused on next get_conn()
			dbmanager.put_conn(conn)
			break

	sheets_creds = json.load(open(sheets_creds_file))

	sheets = Sheets(
        client_id=sheets_creds['client_id'],
        client_secret=sheets_creds['client_secret'],
        refresh_token=sheets_creds['refresh_token'],
	)

	SheetSync(stop, dbmanager, sheets, sheet_id, worksheet_names, edit_url, bustime_start, allocate_ids).run()

	logging.info("Gracefully stopped")
