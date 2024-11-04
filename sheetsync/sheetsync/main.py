
import json
import logging
import signal
import zoneinfo
from collections import defaultdict
from urllib.parse import urlparse

import argh
import gevent.backdoor
import gevent.event
import prometheus_client as prom
from monotonic import monotonic
from psycopg2 import sql
from requests import HTTPError

import common
import common.dateutil
from common.database import DBManager, query, get_column_placeholder
from common.media import check_for_media, download_media
from common.sheets import Sheets as SheetsClient

from .sheets import SheetsEventsMiddleware, SheetsPlaylistsMiddleware, SheetsArchiveMiddleware
from .streamlog import StreamLogClient, StreamLogEventsMiddleware, StreamLogPlaylistsMiddleware

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
	retry_interval = 5
	# Time to wait after getting an error
	error_retry_interval = 10

	# Whether rows that exist in the database but not the sheet should be created in the sheet
	create_missing_ids = False
	# Database table name
	table = NotImplemented
	# Columns to read from the sheet and write to the database
	input_columns = set()
	# Columns to read from the database and write to the sheet
	output_columns = set()
	# Additional columns to read from the database but not write to the sheet,
	# for metrics purposes.
	metrics_columns = set()

	def __init__(self, name, middleware, stop, dbmanager, reverse_sync=False):
		self.name = name
		self.logger = logging.getLogger(type(self).__name__).getChild(name)
		self.middleware = middleware
		self.stop = stop
		self.dbmanager = dbmanager
		if reverse_sync:
			# Reverse Sync refers to copying all data from the database into the sheet,
			# instead of it (mostly) being the other way. In particular:
			# - All columns become output columns (except sheet_name, which can't be changed)
			# - We are allowed to create new sheet rows for database events if they don't exist.
			self.create_missing_ids = True
			self.output_columns = (self.output_columns | self.input_columns) - {"sheet_name"}
			self.input_columns = set()

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

				worksheets, sheet_rows = self.middleware.get_rows()
				for row in sheet_rows:
					if row['id'] in seen:
						self.logger.error("Duplicate id {}, skipping".format(row['id']))
						continue
					seen.add(row['id'])
					self.sync_row(row, db_rows.get(row['id']))

				# Find rows that were not in the sheet, that were expected to be in that sheet.
				missing = [
					r for id, r in db_rows.items()
					if id not in seen
					and self.middleware.row_was_expected(r, worksheets)
				]
				for db_row in missing:
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
				wait(self.stop, sync_start, self.error_retry_interval)
			else:
				self.logger.info("Successful sync")
				sheets_synced.labels(self.name).inc()
				sheet_sync_duration.labels(self.name).observe(monotonic() - sync_start)
				wait(self.stop, sync_start, self.retry_interval)

	def get_db_rows(self):
		"""Return the entire table as a map {id: row namedtuple}"""
		built_query = sql.SQL("""
			SELECT {} FROM {}
		""").format(
			sql.SQL(", ").join(sql.Identifier(col) for col in
				{"id"}
				| self.input_columns
				| self.output_columns
				| self.metrics_columns
			),
			sql.Identifier(self.table),
		)
		result = query(self.conn, built_query)
		by_id = {}
		for row in result.fetchall():
			by_id[row.id] = row
		self.observe_rows(by_id.values())
		return by_id

	def observe_rows(self, rows):
		"""Takes a list of DB rows and updates metrics, optional to implement"""
		pass

	def sync_row(self, sheet_row, db_row):
		"""Take a row dict from the sheet (or None) and a row namedtuple from the database (or None)
		and take whatever action is required to sync them, ie. writing to the database or sheet.
		At least one must be non-None.
		"""

		if db_row is None:
			assert sheet_row
			worksheet = sheet_row["sheet_name"]
			# No row currently in DB, create it.
			self.logger.info("Inserting new DB row {}: {}".format(sheet_row['id'], sheet_row))
			# Insertion conflict just means that another sheet sync beat us to the insert.
			# We can ignore it.
			insert_cols = {'id'} | self.input_columns
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
			sheet_row = self.middleware.create_row(db_row)

		worksheet = sheet_row["sheet_name"]
		rows_found.labels(self.name, worksheet).inc()

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
			""").format(sql.Identifier(self.table), sql.SQL(", ").join([
				sql.SQL("{} = {}").format(
					sql.Identifier(col), get_column_placeholder(col)
				) for col in changed
			]))
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


class EventsSync(SheetSync):
	table = "events"
	input_columns = {
		'sheet_name',
		'event_start',
		'event_end',
		'category',
		'description',
		'submitter_winner',
		'poster_moment',
		'image_links',
		'notes',
		'tags',
	}
	output_columns = {
		'video_link',
		'state',
		'error',
	}
	metrics_columns = {
		"state",
		"error",
		"public",
		"poster_moment",
		"sheet_name",
		"category",
	}

	def __init__(self, name, middleware, stop, dbmanager, reverse_sync=False, media_dir=None, timezone=None, shifts=None):
		super().__init__(name, middleware, stop, dbmanager, reverse_sync)
		self.media_dir = media_dir
		self.media_downloads = None if media_dir is None else {}
		self.timezone = timezone
		self.shifts = shifts
		

	def observe_rows(self, rows):
		counts = defaultdict(lambda: 0)
		for row in rows:
			counts[row.sheet_name, row.category, str(row.poster_moment), row.state, str(bool(row.error))] += 1
		# Reach into metric internals and forget about all previous values,
		# or else any values we don't update will remain as a stale count.
		event_counts._metrics.clear()
		for labels, count in counts.items():
			event_counts.labels(self.name, *labels).set(count)

	def sync_row(self, sheet_row, db_row):
		# Do some special-case transforms for events before syncing

		# Attempt to download any URLs in the links column if we don't already have them.
		# This is done asyncronously. We keep a record of failed attempts for two reasons:
		# - To avoid retrying
		# - To populate the errors column asyncronously
		# This record is just in memory - we're ok retrying after every restart.
		# You can disable downloads on a per-row basis by putting "[nodownload]" in the notes column.
		if sheet_row is not None and self.media_dir is not None and "[nodownload]" not in sheet_row["notes"]:
			for url in sheet_row['image_links']:
				if url not in self.media_downloads:
					self.media_downloads[url] = gevent.spawn(self.download_media, url)
				# Greenlet.exception is populated if the greenlet failed with an exception,
				# or None otherwise (success or not finished).
				# We treat a failure to fetch a URL like a parse error.
				e = self.media_downloads[url].exception
				if e is not None:
					sheet_row.setdefault("_parse_errors", []).append(
						f"Failed to download media link {url:!r}: {e}"
					)

		if db_row is not None:
			# If no database error, but we have parse errors, indicate they should be displayed.
			if db_row.error is None and sheet_row is not None and sheet_row.get('_parse_errors'):
				db_row = db_row._replace(error=", ".join(sheet_row['_parse_errors']))

			# As a presentation detail, we show any row in state DONE with public = False as
			# a virtual state UNLISTED instead, to indicate that it probably still requires other
			# work before being modified to be public = True later.
			if db_row.state == 'DONE' and not db_row.public:
				db_row = db_row._replace(state='UNLISTED')

		super().sync_row(sheet_row, db_row)

	def download_media(self, url):
		hostname = urlparse(url).hostname
		if hostname in ("youtu.be", "youtube.com"):
			self.logger.info(f"Ignoring url {url:!r}: Blocklisted hostname")
		if check_for_media(self.media_dir, url):
			self.logger.info(f"Already have content for url {url:!r}")
			return
		try:
			download_media(url, self.media_dir)
		except Exception:
			self.logger.warning(f"Failed to download url {url:!r}", exc_info=True)
			raise
		self.logger.info(f"Downloaded media for url {url:!r}")


class ArchiveSync(EventsSync):
	# Archive events are a special case of event with less input columns.
	# The other input columns default to empty string in the database.
	input_columns = {
		'sheet_name',
		'event_start',
		'event_end',
		'description',
		'notes',
	}
	output_columns = {
		'state',
		'error',
	}
	# Slower poll rate than events to avoid using large amounts of quota
	retry_interval = 20
	error_retry_interval = 20


class PlaylistsSync(SheetSync):

	# Slower poll rate than events to avoid using large amounts of quota
	retry_interval = 20
	error_retry_interval = 20

	table = "playlists"
	input_columns = {
		"name",
		"description",
		"tags",
		"playlist_id",
		"first_event_id",
		"last_event_id",
		"show_in_description",
		"default_template",
	}


@argh.arg('dbconnect', help=
	"dbconnect should be a postgres connection string, which is either a space-separated "
	"list of key=value pairs, or a URI like:\n"
	"\tpostgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE"
)
@argh.arg('sync-configs',
	metavar="SYNC-CONFIG",
	nargs="+",
	type=json.loads,
	help="""
		A JSON object describing a sync operation to perform.
		Always present:
			name: A human identifier for this sync operation
			backend: The data source. One of "sheets" or "streamlog"
			type: What kind of data is being synced. One of "events", "playlists" or "archive"
		When backend is "sheets":
			creds: path to credentials JSON file containing "client_id", "client_secret" and "refresh_token"
			sheet_id: The id of the Google Sheet to use
			worksheets: List of worksheets within that sheet to sync
			allocate_ids: Boolean, optional. When true, will give rows without ids an id.
				Only one sheetsync acting on the same sheet should have this enabled.
			reverse_sync: Boolean, optional. When true, enables an alternate mode
				where all data is synced from the database to the sheet.
				Only one sheetsync acting on the same sheet should have this enabled.
			When type is "events" or "archive":
				edit_url: a format string for edit links, with {} as a placeholder for id
				bustime_start: Timestamp string at which bustime is 00:00
		When backend is "streamlog":
			type: streamlog
			creds: path to a file containing the auth key
			url: The URL of the streamlog server
			event_id: The id of the streamlog event to sync
	""",
)
@argh.arg('--timezone', help="Local timezone for determining shift times")
@argh.arg('--shifts', type=json.loads, help="""
	Shift definitions in JSON form.
	Always present:
		repeating: a list of repeating shifts. Each of these consist of a sequence of shift name, start hour and end hour. The start and end hours are in local time.
		one_off: a list of non-repeating shifts. Each of these consist of a sequence of shift name, start and end. A start or end time can be a string repersenting timestamp or a URL or null. If it is a URL, the URL will be queried for a timestamp. If no timezone info is provided the timestamp will be assumed to be UTC. If the start time is None, then the start will be assumed to be the earliest possible datetime; if the end is None, it will be assumed to be the oldest possible datetime. If both the start and end are None, the shift will be ignored. 
	""")
def main(dbconnect, sync_configs, metrics_port=8005, backdoor_port=0, media_dir=".", shifts=None, timezone=None):
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
		reverse_sync = config.get("reverse_sync", False)
		if config["backend"] == "sheets":
			allocate_ids = config.get("allocate_ids", False)
			if allocate_ids and reverse_sync:
				raise ValueError("Cannot combine allocate_ids and reverse_sync")
			creds = json.load(open(config["creds"]))
			client = SheetsClient(
				client_id=creds['client_id'],
				client_secret=creds['client_secret'],
				refresh_token=creds['refresh_token'],
			)
			if config["type"] in ("events", "archive"):
				middleware_cls = {
					"events": SheetsEventsMiddleware,
					"archive": SheetsArchiveMiddleware,
				}[config["type"]]
				middleware = middleware_cls(
					client,
					config["sheet_id"],
					config["worksheets"],
					common.dateutil.parse(config["bustime_start"]),
					config["edit_url"],
					allocate_ids,
				)
			elif config["type"] == "playlists":
				middleware = SheetsPlaylistsMiddleware(
					client,
					config["sheet_id"],
					config["worksheets"],
					config.get("allocate_ids", False),
				)
			else:
				raise ValueError("Unknown type {!r}".format(config["type"]))
		elif config["backend"] == "streamlog":
			auth_token = open(config["creds"]).read().strip()
			client = StreamLogClient(
				config["url"],
				config["event_id"],
				auth_token,
			)
			if config["type"] == "events":
				middleware = StreamLogEventsMiddleware(client)
			elif config["type"] == "playlists":
				middleware = StreamLogPlaylistsMiddleware(client, "Tags")
			elif config["type"] == "archive":
				raise ValueError("Archive sync is not compatible with streamlog")
			else:
				raise ValueError("Unknown type {!r}".format(config["type"]))
		else:
			raise ValueError("Unknown backend {!r}".format(config["backend"]))

		sync_class = {
			"events": EventsSync,
			"playlists": PlaylistsSync,
			"archive": ArchiveSync,
		}[config["type"]]
		sync_class_kwargs = {}
		if config["type"] == "events":
			sync_class_kwargs["timezone"] = zoneinfo.ZoneInfo(timezone)
			sync_class_kwargs["shifts"] = shifts
		if config["type"] == "events" and config.get("download_media", False):
			sync_class_kwargs["media_dir"] = media_dir
		sync = sync_class(config["name"], middleware, stop, dbmanager, reverse_sync, **sync_class_kwargs)
		workers.append(sync)

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
