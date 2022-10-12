import datetime
from functools import wraps
import json
import logging
import re

import argh
import base64
import binascii
import flask
import gevent
import gevent.backdoor
from gevent.pywsgi import WSGIServer
import prometheus_client
import psycopg2
from psycopg2 import sql

import common
from common import database
from common.flask_stats import request_stats, after_request

import google.oauth2.id_token
import google.auth.transport.requests

psycopg2.extras.register_uuid()
app = flask.Flask('thrimshim')
app.after_request(after_request)


MAX_TITLE_LENGTH = 100 # Youtube only allows 100-character titles
MAX_DESCRIPTION_LENGTH = 5000 # Youtube only allows 5000-character descriptions


def cors(app):
	"""WSGI middleware that sets CORS headers"""
	HEADERS = [
		("Access-Control-Allow-Credentials", "false"),
		("Access-Control-Allow-Headers", "*"),
		("Access-Control-Allow-Methods", "GET,POST,HEAD"),
		("Access-Control-Allow-Origin", "*"),
		("Access-Control-Max-Age", "86400"),
	]
	def handle(environ, start_response):
		def _start_response(status, headers, exc_info=None):
			headers += HEADERS
			return start_response(status, headers, exc_info)
		return app(environ, _start_response)
	return handle


def authenticate(f):
	"""Authenticate a token against the database.

	Reference: https://developers.google.com/identity/sign-in/web/backend-auth"""
	@wraps(f)
	def auth_wrapper(*args, **kwargs):
		if app.no_authentication:
			return f(*args, editor='NOT_AUTH', **kwargs)

		try:
			userToken = flask.request.json['token']
		except (KeyError, TypeError):
			return 'User token required', 401
		# check whether token is valid
		try:
			idinfo = google.oauth2.id_token.verify_oauth2_token(userToken, google.auth.transport.requests.Request(), None)
			if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
				raise ValueError('Wrong issuer.')
		except ValueError:
			return 'Invalid token. Access denied.', 403 

		# check whether user is in the database
		email = idinfo['email'].lower()
		conn = app.db_manager.get_conn()
		results = database.query(conn, """
			SELECT email
			FROM editors
			WHERE lower(email) = %s""", email)
		row = results.fetchone()
		if row is None:
			return 'Unknown user. Access denied.', 403
	
		return f(*args, editor=email, **kwargs)

	return auth_wrapper


@app.route('/thrimshim/auth-test', methods=['POST'])
@request_stats
@authenticate
def test(editor=None):
	return json.dumps(editor)


# To make nginx proxying simpler, we want to allow /metrics/* to work
@app.route('/metrics/<trailing>')
@request_stats
def metrics_with_trailing(trailing):
	"""Expose Prometheus metrics."""
	return prometheus_client.generate_latest()


@app.route('/metrics')
@request_stats
def metrics():
	"""Expose Prometheus metrics."""
	return prometheus_client.generate_latest()


@app.route('/thrimshim')
@request_stats
def get_all_rows():
	"""Gets all rows from the events table from the database"""
	conn = app.db_manager.get_conn()
	results = database.query(conn, """
		SELECT *
		FROM events
		ORDER BY event_start
	""")
	rows = []
	for row in results:
		row = row._asdict()
		row['id'] = str(row['id'])
		row = {
			key: (
				value.isoformat() if isinstance(value, datetime.datetime)
				else value
			) for key, value in row.items()
		}
		rows.append(row)
	logging.info('All rows fetched')
	return json.dumps(rows)


@app.route('/thrimshim/defaults')
@request_stats
def get_defaults():
	"""Get default info needed by thrimbletrimmer when not loading a specific row."""
	return json.dumps({
		"video_channel": app.default_channel,
		"bustime_start": app.bustime_start,
		"title_prefix": app.title_header,
		"title_max_length": MAX_TITLE_LENGTH - len(app.title_header),
		"upload_locations": app.upload_locations,
	})


@app.route('/thrimshim/<uuid:ident>', methods=['GET'])
@request_stats
def get_row(ident):
	"""Gets the row from the database with id == ident."""
	conn = app.db_manager.get_conn()
	results = database.query(conn, """
		SELECT *
		FROM events
		WHERE id = %s
	""", ident)
	row = results.fetchone()
	if row is None:
		return 'Row id = {} not found'.format(ident), 404
	assert row.id == ident
	response = row._asdict()

	response['id'] = str(response['id'])	
	if response["video_channel"] is None:
		response["video_channel"] = app.default_channel
	response["title_prefix"] = app.title_header
	response["title_max_length"] = MAX_TITLE_LENGTH - len(app.title_header)
	response["bustime_start"] = app.bustime_start
	response["upload_locations"] = app.upload_locations

	# pick default thumbnail template based on start time.
	# pick default frame time as the middle of the video.
	# ignore both if video has no start time yet.
	DEFAULT_TEMPLATES = [
		"zeta",
		"dawn-guard",
		"alpha-flight",
		"night-watch",
	]
	if response['event_start'] is not None:
		start = response['event_start']
		if response['thumbnail_template'] is None:
			pst_hour = (start.hour - 8) % 24
			shift = int(pst_hour / 6)
			response['thumbnail_template'] = DEFAULT_TEMPLATES[shift]
		if response['thumbnail_time'] is None:
			if response['event_end'] is not None:
				# take full duration, and add half to start to get halfway
				duration = response['event_end'] - start
				response['thumbnail_time'] = start + duration / 2
			else:
				# no end time, just use start time as default frame
				response['thumbnail_time'] = start

	# remove any added headers or footers so round-tripping is a no-op
	if (
		app.title_header
		and response["video_title"] is not None
		and response["video_title"].startswith(app.title_header)
	):
		response["video_title"] = response["video_title"][len(app.title_header):]
	if (
		app.description_footer
		and response["video_description"] is not None
		and response["video_description"].endswith(app.description_footer)
	):
		response["video_description"] = response["video_description"][:-len(app.description_footer)]

	logging.info('Row {} fetched'.format(ident))

	def convert(value):
		if isinstance(value, datetime.datetime):
			return value.isoformat()
		if isinstance(value, datetime.timedelta):
			return value.total_seconds()
		if isinstance(value, memoryview) or isinstance(value, bytes):
			return base64.b64encode(bytes(value)).decode()
		raise TypeError(f"Can't convert object of type {value.__class__.__name__} to JSON: {value}")
	return json.dumps(response, default=convert)


@app.route('/thrimshim/<uuid:ident>', methods=['POST'])
@request_stats
@authenticate
def update_row(ident, editor=None):
	"""Updates row of database with id = ident with the edit columns in new_row."""
	new_row = flask.request.json
	override_changes = new_row.get('override_changes', False)
	state_columns = ['state', 'uploader', 'error', 'video_link'] 
	# These have to be set before a video can be set as 'EDITED'
	non_null_columns = [
		'upload_location', 'video_ranges', 'video_transitions',
		'video_channel', 'video_quality', 'video_title',
		'video_description', 'video_tags', 'thumbnail_mode', 'public'
	]
	edit_columns = non_null_columns + [
		'allow_holes', 'uploader_whitelist', 'thumbnail_time', 'thumbnail_template', 'thumbnail_image'
	]
	sheet_columns = [
		'sheet_name', 'event_start', 'event_end',
		'category', 'description', 'notes', 'tags',
	]
	# These columns may be modified when a video is in state 'DONE',
	# and are a subset of edit_columns.
	modifiable_columns = [
		'video_title', 'video_description', 'video_tags', 'public',
		'thumbnail_mode', 'thumbnail_time', 'thumbnail_template', 'thumbnail_image',
	]
	assert set(modifiable_columns) - set(edit_columns) == set()

	# Check vital edit columns are in new_row
	wanted = set(non_null_columns + ['state'] + sheet_columns)
	missing = wanted - set(new_row)
	if missing:
		return 'Fields missing in JSON: {}'.format(', '.join(missing)), 400
	# Get rid of irrelevant columns
	extras = set(new_row) - set(edit_columns + state_columns + sheet_columns)
	for extra in extras:
		del new_row[extra]

	# Include headers and footers
	if 'video_title' in new_row:
		new_row['video_title'] = app.title_header + new_row['video_title']
	if 'video_description' in new_row:
		new_row['video_description'] += app.description_footer

	# Validate youtube requirements on title and description
	if len(new_row['video_title']) > MAX_TITLE_LENGTH:
		return 'Title must be {} characters or less, including prefix'.format(MAX_TITLE_LENGTH), 400
	if len(new_row['video_description']) > MAX_DESCRIPTION_LENGTH:
		return 'Description must be {} characters or less, including footer'.format(MAX_DESCRIPTION_LENGTH), 400
	for char in ['<', '>']:
		if char in new_row['video_title']:
			return 'Title may not contain a {} character'.format(char), 400
		if char in new_row['video_description']:
			return 'Description may not contain a {} character'.format(char), 400
	# Validate and convert video ranges and transitions.
	num_ranges = len(new_row['video_ranges'])
	if num_ranges == 0:
		return 'Ranges must contain at least one range', 400
	if len(new_row['video_transitions']) != num_ranges - 1:
		return 'There must be exactly {} transitions for {} ranges'.format(
			num_ranges - 1, num_ranges,
		)
	for start, end in new_row['video_ranges']:
		if start > end:
			return 'Range start must be less than end', 400
	# We need these to be tuples not lists for psycopg2 to do the right thing,
	# but since they come in as JSON they are currently lists.
	new_row['video_ranges'] = [tuple(range) for range in new_row['video_ranges']]
	new_row['video_transitions'] = [
		None if transition is None else tuple(transition)
		for transition in new_row['video_transitions']
	]

	# Convert binary fields from base64 and do basic validation of contents
	if new_row.get('thumbnail_image') is not None:
		if new_row['thumbnail_mode'] != 'CUSTOM':
			return 'Can only upload custom image when thumbnail_mode = "CUSTOM"', 400
		try:
			new_row['thumbnail_image'] = base64.b64decode(new_row['thumbnail_image'])
		except binascii.Error:
			return 'thumbnail_image must be valid base64', 400
		# check for PNG file header
		if not new_row['thumbnail_image'].startswith(b'\x89PNG\r\n\x1a\n'):
			return 'thumbnail_image must be a PNG', 400

	conn = app.db_manager.get_conn()
	# Check a row with id = ident is in the database
	built_query = sql.SQL("""
		SELECT id, state, {} 
		FROM events
		WHERE id = %s
	""").format(sql.SQL(', ').join(
		sql.Identifier(key) for key in sheet_columns
	))
	results = database.query(conn, built_query, ident)
	old_row = results.fetchone()._asdict()
	if old_row is None:
		return 'Row {} not found'.format(ident), 404
	assert old_row['id'] == ident

	if new_row['state'] == 'MODIFIED':
		if old_row['state'] not in ['DONE', 'MODIFIED']:
			return 'Video is in state {} and cannot be modified'.format(old_row['state']), 403
	elif old_row['state'] not in ['UNEDITED', 'EDITED', 'CLAIMED']:
		return 'Video already published', 403

	# check whether row has been changed in the sheet since editing has begun
	changes = ''
	for column in sheet_columns:
		if isinstance(old_row[column], datetime.datetime):
			old_row[column] = old_row[column].isoformat()
		def normalize(value):
			if isinstance(value, list):
				return sorted(map(normalize, value))
			if value is None:
				return None
			return value.lower().strip()
		if normalize(new_row[column]) != normalize(old_row[column]):
			changes += '{}: {} => {}\n'.format(column, new_row[column], old_row[column])
	if changes and not override_changes:
		return 'Sheet columns have changed since editing has begun. Please review changes\n' + changes, 409

	if new_row['state'] == 'MODIFIED':
		# Modifying published rows is more limited, we ignore all other fields.
		for column in set(modifiable_columns) & set(non_null_columns):
			if new_row[column] is None:
				missing.append(column)
		if missing:
			return 'Fields {} must be non-null for modified video'.format(', '.join(missing)), 400
		build_query = sql.SQL("""
			UPDATE events
			SET last_modified = NOW(), error = NULL, state = 'MODIFIED', {}
			WHERE id = %(id)s AND state IN ('DONE', 'MODIFIED')
		""").format(sql.SQL(", ").join(
			sql.SQL("{} = {}").format(
				sql.Identifier(column), database.get_column_placeholder(column),
			) for column in modifiable_columns
		))
		result = database.query(conn, build_query, id=ident, **new_row)
		if result.rowcount != 1:
			return 'Video changed state while we were updating - maybe it was reset?', 403

	else:
		# handle state columns
		if new_row['state'] == 'EDITED':
			missing = []
			for column in non_null_columns:
				if new_row[column] is None:
					missing.append(column)
			if missing:
				return 'Fields {} must be non-null for video to be cut'.format(', '.join(missing)), 400
			if len(new_row.get('video_title', '')) <= len(app.title_header):
				return 'Video title must not be blank', 400
			if len(new_row.get('video_description', '')) <= len(app.description_footer):
				return 'Video description must not be blank. If you have nothing else to say, just repeat the title.', 400
		elif new_row['state'] != 'UNEDITED':
			return 'Invalid state {}'.format(new_row['state']), 400
		new_row['uploader'] = None
		new_row['error'] = None
		new_row['editor'] = editor
		new_row['edit_time'] = datetime.datetime.utcnow()

		# actually update database
		build_query = sql.SQL("""
			UPDATE events
			SET {}
			WHERE id = %(id)s
			AND state IN ('UNEDITED', 'EDITED', 'CLAIMED')"""
		).format(sql.SQL(", ").join(
			sql.SQL("{} = {}").format(
				sql.Identifier(column), database.get_column_placeholder(column),
			) for column in new_row.keys() if column not in sheet_columns
		))
		result = database.query(conn, build_query, id=ident, **new_row)
		if result.rowcount != 1:
			return 'Video likely already published', 403	
			
	logging.info('Row {} updated to state {}'.format(ident, new_row['state']))
	return ''


@app.route('/thrimshim/manual-link/<uuid:ident>', methods=['POST'])
@request_stats
@authenticate
def manual_link(ident, editor=None):
	"""Manually set a video_link if the state is 'UNEDITED' or 'DONE' and the 
	upload_location is 'manual' or 'youtube-manual'."""
	link = flask.request.json['link']
	upload_location = flask.request.json.get('upload_location', 'manual')

	if upload_location == 'youtube-manual':
		YOUTUBE_URL_RE = r'^https?://(?:youtu\.be/|youtube.com/watch\?v=)([a-zA-Z0-9_-]{11})$'
		match = re.match(YOUTUBE_URL_RE, link)
		if not match:
			return 'Link does not appear to be a youtube.com or youtu.be video link. Try removing any extra query params (after the video id).', 400
		video_id, = match.groups()
	elif upload_location == 'manual':
		video_id = None
	else:
		return 'Upload location must be "manual" or "youtube-manual"', 400

	conn = app.db_manager.get_conn()
	results = database.query(conn, """
		SELECT id, state
		FROM events
		WHERE id = %s""", ident)
	old_row = results.fetchone()
	if old_row is None:
		return 'Row {} not found'.format(ident), 404
	if old_row.state != 'UNEDITED':
		return 'Invalid state {} for manual video link'.format(old_row.state), 403		
	now = datetime.datetime.utcnow()
	# note we force thumbnail mode of manual uploads to always be NONE,
	# since they might not be a video we actually control at all, or might not even be on youtube.
	results = database.query(conn, """
		UPDATE events 
		SET state='DONE', upload_location = %s, video_link = %s, video_id = %s,
			editor = %s, edit_time = %s, upload_time = %s, thumbnail_mode = 'NONE'
		WHERE id = %s AND state = 'UNEDITED'
	""", upload_location, link, video_id, editor, now, now, ident)
	logging.info("Row {} video_link set to {}".format(ident, link))
	return ''	
	

@app.route('/thrimshim/reset/<uuid:ident>', methods=['POST'])
@request_stats
@authenticate
def reset_row(ident, editor=None):
	"""Clear state and video_link columns and reset state to 'UNEDITED'.
	If force is 'true', it will do so regardless of current state.
	Otherwise, it will only do so if we know no video has been uploaded
	(state is UNEDITED, EDITED or CLAIMED)
	"""
	force = (flask.request.args.get('force', '').lower() == "true")
	conn = app.db_manager.get_conn()
	query = """
		UPDATE events 
		SET state='UNEDITED', error = NULL, video_id = NULL, video_link = NULL,
			uploader = NULL, editor = NULL, edit_time = NULL, upload_time = NULL,
			last_modified = NULL
		WHERE id = %s {}
	""".format(
		"" if force else "AND state IN ('UNEDITED', 'EDITED', 'CLAIMED')",
	)
	results = database.query(conn, query, ident)
	if results.rowcount != 1:
		return 'Row id = {} not found or not in cancellable state'.format(ident), 404
	logging.info("Row {} reset to 'UNEDITED'".format(ident))
	return ''	
		

@argh.arg('--host', help='Address or socket server will listen to. Default is 0.0.0.0 (everything on the local machine).')
@argh.arg('--port', help='Port server will listen on. Default is 8004.')
@argh.arg('connection-string', help='Postgres connection string, which is either a space-separated list of key=value pairs, or a URI like: postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE')
@argh.arg('default-channel', help='The default video_channel sent to the editor and assumed if not given on write')
@argh.arg('bustime-start', help='The start time in UTC for the event, for UTC-Bustime conversion')
@argh.arg('--backdoor-port', help='Port for gevent.backdoor access. By default disabled.')
@argh.arg('--no-authentication', help='Bypass authentication (act as though all calls are authenticated)')
@argh.arg('--title-header', help='A header to prefix all titles with, seperated from the submitted title by " - "')
@argh.arg('--description-footer', help='A footer to suffix all descriptions with, seperated from the submitted description by a blank line.')
@argh.arg('--upload-locations', help='A comma-seperated list of valid upload locations, to pass to thrimbletrimmer. The first is the default. Note this is NOT validated on write.')
def main(
	connection_string, default_channel, bustime_start, host='0.0.0.0', port=8004, backdoor_port=0,
	no_authentication=False, title_header=None, description_footer=None, upload_locations='',
):
	server = WSGIServer((host, port), cors(app))

	app.no_authentication = no_authentication
	app.default_channel = default_channel
	app.bustime_start = bustime_start
	app.title_header = "" if title_header is None else "{} - ".format(title_header)
	app.description_footer = "" if description_footer is None else "\n\n{}".format(description_footer)
	app.upload_locations = upload_locations.split(',') if upload_locations else []
	app.db_manager = database.DBManager(dsn=connection_string)

	common.PromLogCountsHandler.install()
	common.install_stacksampler()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	if app.no_authentication:
		logging.warning('Not authenticating POST requests')

	common.serve_with_graceful_shutdown(server)
