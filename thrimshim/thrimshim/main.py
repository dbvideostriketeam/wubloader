import datetime
from functools import wraps
import json
import logging
import signal

import argh
import flask
import gevent
import gevent.backdoor
from gevent.pywsgi import WSGIServer
import prometheus_client
import psycopg2
from psycopg2 import sql

from common import database, PromLogCountsHandler, install_stacksampler
from common.flask_stats import request_stats, after_request

import google.oauth2.id_token
import google.auth.transport.requests

psycopg2.extras.register_uuid()
app = flask.Flask('thrimshim')
app.after_request(after_request)

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
		FROM events""")
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


@app.route('/thrimshim/<uuid:ident>', methods=['GET'])
@request_stats
def get_row(ident):
	"""Gets the row from the database with id == ident."""
	conn = app.db_manager.get_conn()
	results = database.query(conn, """
		SELECT *
		FROM events
		WHERE id = %s""", ident)
	row = results.fetchone()
	if row is None:
		return 'Row id = {} not found'.format(ident), 404
	assert row.id == ident
	response = row._asdict()

	response['id'] = str(response['id'])	
	response = {
		key: (
			value.isoformat() if isinstance(value, datetime.datetime)
			else value
		) for key, value in response.items()
	}
	logging.info('Row {} fetched'.format(ident))
	return json.dumps(response)

@app.route('/thrimshim/<uuid:ident>', methods=['POST'])
@request_stats
@authenticate
def update_row(ident, editor=None):
	new_row = flask.request.json
	"""Updates row of database with id = ident with the edit columns in
	new_row."""

	state_columns = ['state', 'uploader', 'error', 'video_link'] 
	#these have to be set before a video can be set as 'EDITED'
	non_null_columns = ['upload_location', 'video_start', 'video_end',
		'video_channel', 'video_quality', 'video_title', 'video_description']
	edit_columns = non_null_columns + ['allow_holes', 'uploader_whitelist']

	#check vital edit columns are in new_row
	wanted = set(non_null_columns + ['state'])
	missing = wanted - set(new_row)
	if missing:
		return 'Fields missing in JSON: {}'.format(', '.join(missing)), 400
	#get rid of irrelevant columns
	extras = set(new_row) - set(edit_columns + state_columns)
	for extra in extras:
		del new_row[extra]

	#validate title length - YouTube titles are limited to 100 characters.
	if len(new_row['video_title']) > 100:
		return 'Title must be 100 characters or less', 400
	#validate start time is less than end time
	if new_row['video_start'] > new_row['video_end']:
		return 'Video Start must be less than Video End.', 400

	conn = app.db_manager.get_conn()
	#check a row with id = ident is in the database
	results = database.query(conn, """
		SELECT id, state 
		FROM events
		WHERE id = %s""", ident)
	old_row = results.fetchone()
	if old_row is None:
		return 'Row {} not found'.format(ident), 404
	assert old_row.id == ident
	

	if old_row.state not in ['UNEDITED', 'EDITED', 'CLAIMED']:
		return 'Video already published', 403
	
	# handle state columns
	if new_row['state'] == 'EDITED':
		missing = []
		for column in non_null_columns:
			if not new_row[column]:
				missing.append(column)
		if missing:
			return 'Fields {} must be non-null for video to be cut'.format(', '.join(missing)), 400
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
				sql.Identifier(column), sql.Placeholder(column),
			) for column in new_row.keys()
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
	upload_location is 'manual'."""
	link = flask.request.json['link']
	conn = app.db_manager.get_conn()
	results = database.query(conn, """
		SELECT id, state, upload_location 
		FROM events
		WHERE id = %s""", ident)
	old_row = results.fetchone()
	if old_row is None:
		return 'Row {} not found'.format(ident), 404
	if old_row.state != 'UNEDITED' and not (old_row.state == 'DONE' and old_row.upload_location == 'manual'):
		return 'Invalid state {} for manual video link'.format(old_row.state), 403		
	now = datetime.datetime.utcnow()
	results = database.query(conn, """
		UPDATE events 
		SET state='DONE', upload_location = 'manual', video_link = %s,
			editor = %s, edit_time = %s, upload_time = %s
		WHERE id = %s AND (state = 'UNEDITED' OR (state = 'DONE' AND
			upload_location = 'manual'))""", link, editor, now, now, ident)
	logging.info("Row {} video_link set to {}".format(ident, link))
	return ''	
	

@app.route('/thrimshim/reset/<uuid:ident>', methods=['POST'])
@request_stats
@authenticate
def reset_row(ident, editor=None):
	"""Clear state and video_link columns and reset state to 'UNEDITED'."""
	conn = app.db_manager.get_conn()
	results = database.query(conn, """
		UPDATE events 
		SET state='UNEDITED', error = NULL, video_id = NULL, video_link = NULL,
			uploader = NULL, editor = NULL, edit_time = NULL, upload_time = NULL
		WHERE id = %s""", ident)
	if results.rowcount != 1:
		return 'Row id = {} not found'.format(ident), 404
	logging.info("Row {} reset to 'UNEDITED'".format(ident))
	return ''	
		

@argh.arg('--host', help='Address or socket server will listen to. Default is 0.0.0.0 (everything on the local machine).')
@argh.arg('--port', help='Port server will listen on. Default is 8004.')
@argh.arg('connection-string', help='Postgres connection string, which is either a space-separated list of key=value pairs, or a URI like: postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE')
@argh.arg('--backdoor-port', help='Port for gevent.backdoor access. By default disabled.')
@argh.arg('--no-authentication', help='Do not authenticate')
def main(connection_string, host='0.0.0.0', port=8004, backdoor_port=0,
	no_authentication=False):
	"""Thrimshim service."""
	server = WSGIServer((host, port), cors(app))
	app.db_manager = database.DBManager(dsn=connection_string)
	app.no_authentication = no_authentication

	def stop():
		logging.info('Shutting down')
		server.stop()
	gevent.signal(signal.SIGTERM, stop)

	PromLogCountsHandler.install()
	install_stacksampler()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	logging.info('Starting up')
	if app.no_authentication:
		logging.warning('Not authenticating POST requests')
	server.serve_forever()
	logging.info("Gracefully shut down")
