import datetime
import json
import logging
import signal
import uuid

import argh
import flask
import gevent
import gevent.backdoor
from gevent.pywsgi import WSGIServer
import prometheus_client
from psycopg2 import sql

import common
from common import database

app = flask.Flask('thrimshim')

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


@app.route('/metrics')
def metrics():
	"""Expose Prometheus metrics."""
	return prometheus_client.generate_latest()


@app.route('/thrimshim/<ident>', methods=['GET', 'POST'])
def thrimshim(ident):
	"""Comunicate between Thrimbletrimmer and the Wubloader database."""
	try:
		uuid.UUID(ident)
	except ValueError:
		return 'Invalid format for id', 400
	if flask.request.method == 'POST':
		row = flask.request.json
		return update_row(ident, row)
	else:
		return get_row(ident)
		
		
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

	response = {
		key: (
			value.isoformat() if isinstance(value, datetime.datetime)
			else value
		) for key, value in response.items()
	}
	return json.dumps(response)


def update_row(ident, new_row):
	"""Updates row of database with id = ident with the edit columns in
	new_row.

	If a 'video_link' is provided in update, interpret this as a manual video
	upload and set state to 'DONE'. If state currently is 'DONE', and a empty
	'video_link' is present, reset state to 'UNEDITED'."""

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
	

	if old_row.state not in ['UNEDITED', 'EDITED', 'CLAIMED'] and not ('video_link' in new_row and new_row['video_link']):
		return 'Video already published', 403
	
	# handle state columns
	# interpret non-empty video_link as manual uploads
	# interpret state == 'DONE' and an empty video link as instructions to reset
	# state to 'UNEDITED' and clear video link
	# otherwise clear other state columns
	if 'video_link' in new_row and new_row['video_link']:
		new_row['state'] = 'DONE'
		new_row['upload_location'] = 'manual'
	else:
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

	# actually update database
	query_str = """
		UPDATE events
		SET {{}}
		WHERE id = %(id)s
		{}""".format("AND state IN ('UNEDITED', 'EDITED', 'CLAIMED')" if not ('video_link' in new_row and new_row['video_link']) else "")
	build_query = sql.SQL(query_str).format(sql.SQL(", ").join(
		sql.SQL("{} = {}").format(
			sql.Identifier(column), sql.Placeholder(column),
		) for column in new_row.keys()
		))
	result = database.query(conn, build_query, id=ident, **new_row)
	if result.rowcount != 1:
		return 'Video likely already published', 403	
			
	logging.info('Row {} updated to state {}'.format(ident, new_row['state']))
	return ''

@app.route('/thrimshim/reset/<ident>')
def reset_row(ident):
	"""Clear state and video_link columns and reset state to 'UNEDITED'."""
	try:
		uuid.UUID(ident)
	except ValueError:
		return 'Invalid format for id', 400
	conn = app.db_manager.get_conn()
	results = database.query(conn, """
		UPDATE events 
		SET STATE='UNEDITED', error = NULL, video_id = NULL, video_link = NULL,
		uploader = NULL
		WHERE id = %s""", ident)
	if results.rowcount != 1:
		return 'Row id = {} not found'.format(ident), 404
	logging.info("Row {} reset to 'UNEDITED'".format(ident))
	return ''	
		

@argh.arg('--host', help='Address or socket server will listen to. Default is 0.0.0.0 (everything on the local machine).')
@argh.arg('--port', help='Port server will listen on. Default is 8004.')
@argh.arg('--connection-string', help='Postgres connection string, which is either a space-separated list of key=value pairs, or a URI like: postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE')
@argh.arg('--backdoor-port', help='Port for gevent.backdoor access. By default disabled.')
def main(host='0.0.0.0', port=8004, connection_string='', backdoor_port=0):
	"""Thrimshim service."""
	server = WSGIServer((host, port), cors(app))
	app.db_manager = database.DBManager(dsn=connection_string)

	def stop():
		logging.info("Shutting down")
		server.stop()
	gevent.signal(signal.SIGTERM, stop)

	common.PromLogCountsHandler.install()
	common.install_stacksampler()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	logging.info("Starting up")
	server.serve_forever()
	logging.info("Gracefully shut down")
