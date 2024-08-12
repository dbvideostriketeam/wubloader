
import json
import logging
import signal
from collections import defaultdict

import argh
import gevent.backdoor
import gevent.event
import prometheus_client as prom
from monotonic import monotonic
from psycopg2 import sql
from psycopg2.extras import execute_values
from requests import HTTPError

import common
import common.dateutil
from common.database import DBManager, query, get_column_placeholder

from .sheets import SheetsClient, SheetsMiddleware
from .streamlog import StreamLogClient, StreamLogMiddleware

sheets_synced = prom.Counter(
	'sheets_synced',
	'Number of successful sheet syncs',
	['name'],
)

sheet_sync_duration = prom.Histogram(
	'sheet_sync_duration',
	'Time taken to complete a sheet sync',
	['name'],
)

sync_errors = prom.Counter(
	'sync_errors',
	'Number of errors syncing sheets',
	['name'],
)

rows_found = prom.Counter(
	'rows_found',
	'Number of rows that sheetsync looked at with an id',
	['name', 'worksheet'],
)

rows_changed = prom.Counter(
	'rows_changed',
	'Number of rows that needed changes applied, with type=insert, type=input or type=output',
	['name', 'type', 'worksheet'],
)

event_counts = prom.Gauge(
	'event_counts',
	'Number of rows in the database',
	['name', 'sheet_name', 'category', 'poster_moment', 'state', 'errored'],
)


def wait(event, base, interval):
	"""Wait until INTERVAL seconds after BASE, or until event is set."""
	now = monotonic()
	to_wait = base + common.jitter(interval) - now
	if to_wait > 0:
		event.wait(to_wait)


class SheetSync(object):

	# Time between syncs
	RETRY_INTERVAL = 5

	# Time to wait after getting an error
	ERROR_RETRY_INTERVAL = 10

	def __init__(self, name, middleware, stop, dbmanager, reverse_sync=False):
		self.name = name
		self.logger = logging.getLogger(type(self).__name__).getChild(name)
		self.middleware = middleware
		self.stop = stop
		self.dbmanager = dbmanager
		self.create_missing_ids = False
		self.table = "events"
		# List of input columns
		self.input_columns = [
			'sheet_name'
			'event_start',
			'event_end',
			'category',
			'description',
			'submitter_winner',
			'poster_moment',
			'image_links',
			'notes',
			'tags',
		]
		# List of output columns
		self.output_columns = [
			'video_link',
			'state',
			'error',
		]
		if reverse_sync:
			# Reverse Sync refers to copying all event data from the database into the sheet,
			# instead of it (mostly) being the other way. In particular:
			# - All columns become output columns (except sheet_name, which can't be changed)
			# - We are allowed to create new sheet rows for database events if they don't exist.
			self.create_missing_ids = True
			self.output_columns += self.input_columns
			self.output_columns.remove("sheet_name")
			self.input_columns = []

	def run(self):
		self.conn = self.dbmanager.get_conn()

		while not self.stop.is_set():

			try:
				sync_start = monotonic()
				# Since the full dataset is small, the cost of round tripping to the database to check
				# each row is more expensive than the cost of just grabbing the entire table
				# and comparing locally.
				db_rows = self.get_db_rows()
				seen = set()

				for row in self.middleware.get_rows():
					if row['id'] in seen:
						self.logger.error("Duplicate id {}, skipping".format(row['id']))
						continue
					seen.add(row['id'])
					self.sync_row(row, db_rows.get(row['id']))

				for db_row in [r for id, r in db_rows.items() if id not in seen]:
					self.sync_row(None, db_row)

			except Exception as e:
				# for HTTPErrors, http response body includes the more detailed error
				detail = ''
				if isinstance(e, HTTPError):
					detail = ": {}".format(e.response.content)
				self.logger.exception("Failed to sync{}".format(detail))
				sync_errors.labels(self.name).inc()
				# To ensure a fresh slate and clear any DB-related errors, get a new conn on error.
				# This is heavy-handed but simple and effective.
				# If we can't re-connect, the program will crash from here,
				# then restart and wait until it can connect again.
				self.conn = self.dbmanager.get_conn()
				wait(self.stop, sync_start, self.ERROR_RETRY_INTERVAL)
			else:
				self.logger.info("Successful sync")
				sheets_synced.labels(self.name).inc()
				sheet_sync_duration.labels(self.name).observe(monotonic() - sync_start)
				wait(self.stop, sync_start, self.RETRY_INTERVAL)

	def get_db_rows(self):
		"""Return the entire table as a map {id: row namedtuple}"""
		built_query = sql.SQL("""
			SELECT {} FROM {}
		""").format(
			sql.SQL(", ").join(sql.Identifier(col) for col in
				{ "id", "state", "error", "public", "poster_moment", "sheet_name", "category" }
				| set(self.input_columns)
				| set(self.output_columns)
			),
			sql.Identifier("table"),
		)
		result = query(self.conn, built_query)
		by_id = {}
		counts = defaultdict(lambda: 0)
		for row in result.fetchall():
			by_id[row.id] = row
			counts[row.sheet_name, row.category, str(row.poster_moment), row.state, str(bool(row.error))] += 1
		# Reach into metric internals and forget about all previous values,
		# or else any values we don't update will remain as a stale count.
		event_counts._metrics.clear()
		for labels, count in counts.items():
			event_counts.labels(self.name, *labels).set(count)
		return by_id

	def sync_row(self, sheet_row, db_row):
		"""Take a row dict from the sheet (or None) and a row namedtuple from the database (or None)
		and take whatever action is required to sync them, ie. writing to the database or sheet.
		At least one must be non-None.
		"""

		if db_row is None:
			assert sheet_row
			worksheet = sheet_row["sheet_name"]
			# No row currently in DB, create it.
			self.logger.info("Inserting new DB row {}".format(sheet_row['id']))
			# Insertion conflict just means that another sheet sync beat us to the insert.
			# We can ignore it.
			insert_cols = ['id'] + self.input_columns
			built_query = sql.SQL("""
				INSERT INTO {} ({})
				VALUES ({})
				ON CONFLICT DO NOTHING
			""").format(
				sql.Identifier(self.table),
				sql.SQL(", ").join(sql.Identifier(col) for col in insert_cols),
				sql.SQL(", ").join(get_column_placeholder(col) for col in insert_cols),
			)
			query(self.conn, built_query, **sheet_row)
			rows_found.labels(self.name, worksheet).inc()
			rows_changed.labels(self.name, 'insert', worksheet).inc()
			self.middleware.mark_modified(sheet_row)
			return

		if sheet_row is None:
			assert db_row
			if not self.create_missing_ids:
				self.logger.info("Skipping db row {} without any matching sheet row".format(db_row.id))
				return
			self.logger.info("Adding new row {}".format(db_row.id))
			sheet_row = self.middleware.create_row(db_row.sheet_name, db_row.id)

		worksheet = sheet_row["sheet_name"]
		rows_found.labels(self.name, worksheet).inc()

		# If no database error, but we have parse errors, indicate they should be displayed.
		if db_row.error is None and sheet_row.get('_parse_errors'):
			db_row = db_row._replace(error=", ".join(sheet_row['_parse_errors']))

		# As a presentation detail, we show any row in state DONE with public = False as
		# a virtual state UNLISTED instead, to indicate that it probably still requires other
		# work before being modified to be public = True later.
		if db_row.state == 'DONE' and not db_row.public:
			db_row = db_row._replace(state='UNLISTED')

		# Update database with any changed inputs
		changed = [col for col in self.input_columns if sheet_row.get(col) != getattr(db_row, col)]
		if changed:
			self.logger.info("Updating db row {} with new value(s) for {}".format(
				sheet_row['id'], ', '.join(changed)
			))
			built_query = sql.SQL("""
				UPDATE {}
				SET {}
				WHERE id = %(id)s
			""").format(sql.SQL(", ").join(
				[sql.Identifer(self.table)] +
				[sql.SQL("{} = {}").format(
					sql.Identifier(col), get_column_placeholder(col)
				) for col in changed]
			))
			query(self.conn, built_query, **sheet_row)
			rows_changed.labels(self.name, 'input', worksheet).inc()
			self.middleware.mark_modified(sheet_row)

		# Update sheet with any changed outputs
		changed = [col for col in self.output_columns if sheet_row.get(col) != getattr(db_row, col)]
		if changed:
			self.logger.info("Updating sheet row {} with new value(s) for {}".format(
				sheet_row['id'], ', '.join(changed)
			))
			for col in changed:
				self.logger.debug("Writing to sheet {} {!r} -> {!r}".format(col, sheet_row.get(col), getattr(db_row, col)))
				self.middleware.write_value(
					sheet_row, col, getattr(db_row, col),
				)
			rows_changed.labels(self.name, 'output', worksheet).inc()
			self.middleware.mark_modified(sheet_row)


class PlaylistSync:

	# Time between syncs
	RETRY_INTERVAL = 20

	# Time to wait after getting an error
	ERROR_RETRY_INTERVAL = 20

	def __init__(self, stop, dbmanager, sheets, sheet_id, worksheet):
		self.stop = stop
		self.dbmanager = dbmanager
		self.sheets = sheets
		self.sheet_id = sheet_id
		self.worksheet = worksheet

	def run(self):
		self.conn = self.dbmanager.get_conn()

		while not self.stop.is_set():
			try:
				sync_start = monotonic()
				rows = self.sheets.get_rows(self.sheet_id, self.worksheet)
				self.sync_playlists(rows)
			except Exception as e:
				# for HTTPErrors, http response body includes the more detailed error
				detail = ''
				if isinstance(e, HTTPError):
					detail = ": {}".format(e.response.content)
				logging.exception("Failed to sync{}".format(detail))
				sync_errors.labels("playlists").inc()
				# To ensure a fresh slate and clear any DB-related errors, get a new conn on error.
				# This is heavy-handed but simple and effective.
				# If we can't re-connect, the program will crash from here,
				# then restart and wait until it can connect again.
				self.conn = self.dbmanager.get_conn()
				wait(self.stop, sync_start, self.ERROR_RETRY_INTERVAL)
			else:
				logging.info("Successful sync of playlists")
				sheets_synced.labels("playlists").inc()
				sheet_sync_duration.labels("playlists").observe(monotonic() - sync_start)
				wait(self.stop, sync_start, self.RETRY_INTERVAL)

	def sync_playlists(self, rows):
		"""Parse rows with a valid playlist id and at least one tag,
		overwriting the entire playlists table"""
		playlists = []
		for row in rows:
			if len(row) == 5:
				tags, _, name, playlist_id, show_in_description = row
			elif len(row) == 4:
				tags, _, name, playlist_id = row
				show_in_description = ""
			else:
				continue
			tags = [tag.strip() for tag in tags.split(',') if tag.strip()]
			if not tags:
				continue
			# special-case for the "all everything" list,
			# we don't want "no tags" to mean "all videos" so we need a sentinel value.
			if tags == ["<all>"]:
				tags = []
			playlist_id = playlist_id.strip()
			if len(playlist_id) != 34 or not playlist_id.startswith('PL'):
				continue
			show_in_description = show_in_description == "[✓]"
			playlists.append((playlist_id, tags, name, show_in_description))
		# We want to wipe and replace all the current entries in the table.
		# The easiest way to do this is a DELETE then an INSERT, all within a transaction.
		# The "with" block will perform everything under it within a transaction, rolling back
		# on error or committing on exit.
		logging.info("Updating playlists table with {} playlists".format(len(playlists)))
		with self.conn:
			query(self.conn, "DELETE FROM playlists")
			execute_values(self.conn.cursor(), "INSERT INTO playlists(playlist_id, tags, name, show_in_description) VALUES %s", playlists)


@argh.arg('dbconnect', help=
	"dbconnect should be a postgres connection string, which is either a space-separated "
	"list of key=value pairs, or a URI like:\n"
	"\tpostgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE"
)
@argh.arg('sync-configs',
	metavar="SYNC-CONFIG",
	nargs="+",
	type=json.loads,
	help="\n".join([
		'A JSON object describing a sync operation to perform. One of:',
		'  type: "sheets"',
		'  creds: path to credentials JSON file containing "client_id", "client_secret" and "refresh_token"',
		'  sheet_id: The id of the Google Sheet to use',
		'  worksheets: List of worksheets within that sheet to sync',
		'  edit_url: a format string for edit links, with {} as a placeholder for id',
		'  bustime_start: Timestamp string at which bustime is 00:00',
		'  allocate_ids: Boolean, optional. When true, will give rows without ids an id.',
		'    Only one sheetsync acting on the same sheet should have this enabled.',
		'  reverse_sync: Boolean, optional. When true, enables an alternate mode',
		'    where all data is synced from the database to the sheet',
		'  playlist_worksheet: An optional additional worksheet name that holds playlist tag definitions',
		'or:',
		'  type: streamlog',
		'  creds: path to a file containing the auth key',
		'  url: The URL of the streamlog server',
		'  event_id: The id of the streamlog event to sync',
	]),
)
def main(dbconnect, sync_configs, metrics_port=8005, backdoor_port=0):
	"""
	Sheet sync constantly scans a Google Sheets sheet and a database, copying inputs from the sheet
	to the DB and outputs from the DB to the sheet.

	With the exception of id allocation or reverse sync mode, all operations are idempotent and multiple sheet syncs
	may be run for redundancy.
	"""
	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	stop = gevent.event.Event()
	gevent.signal_handler(signal.SIGTERM, stop.set) # shut down on sigterm

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

	workers = []

	for config in sync_configs:
		if config["type"] == "sheets":
			creds = json.load(open(config["creds"]))
			client = SheetsClient(
				client_id=creds['client_id'],
				client_secret=creds['client_secret'],
				refresh_token=creds['refresh_token'],
			)
			middleware = SheetsMiddleware(
				client,
				config["sheet_id"],
				config["worksheets"],
				common.dateutil.parse(config["bustime_start"]),
				config["edit_url"],
				config.get("allocate_ids", False),
			)
			if "playlist_worksheet" in config:
				workers.append(
					PlaylistSync(stop, dbmanager, client, config["sheet_id"], config["playlist_worksheet"])
				)
		elif config["type"] == "streamlog":
			auth_token = open(config["creds"]).read().strip()
			client = StreamLogClient(
				config["url"],
				config["event_id"],
				auth_token,
			)
			middleware = StreamLogMiddleware(client)
		else:
			raise ValueError("Unknown type {!r}".format(config["type"]))
		workers.append(
			SheetSync(config["type"], middleware, stop, dbmanager, config.get("reverse_sync", False)),
		)

	jobs = [gevent.spawn(worker.run) for worker in workers]
	# Block until any one exits
	gevent.wait(jobs, count=1)
	# Stop the others if they aren't stopping already
	stop.set()
	# Block until all have exited
	gevent.wait(jobs)
	# Call get() for each one to re-raise if any errored
	for job in jobs:
		job.get()

	logging.info("Gracefully stopped")
