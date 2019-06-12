import datetime
import json
import logging
import signal
import uuid

import argh
import gevent
import gevent.backdoor
from gevent.pywsgi import WSGIServer
import flask
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

	If a 'video_link' is provided in update, interperet this as a manual video
	upload and set state to 'DONE'"""

	edit_columns = ['allow_holes', 'uploader_whitelist', 'upload_location',
				'video_start', 'video_end', 'video_title', 'video_description',
				'video_channel', 'video_quality']
	state_columns = ['state', 'uploader', 'error', 'video_link'] 
	#these have to be set before a video can be set as 'EDITED'
	non_null_columns = ['upload_location', 'video_start', 'video_end',
		'video_channel', 'video_quality']

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
	with database.transaction(conn):
		results = database.query(conn, """
			SELECT id, state 
			FROM events
			WHERE id = %s;""", ident)
	old_row = results.fetchone()
	if old_row is None:
		return 'Row {} not found'.format(ident), 404
	assert old_row.id == ident
	
	if old_row.state not in ['UNEDITED', 'EDITED', 'CLAIMED']:
		return 'Video already published', 403
	
	# handle state columns
	# handle non-empty video_link as manual uploads
	# otherwise clear other state columns
	if 'video_link' in new_row and new_row['video_link']:
		new_row['state'] = 'DONE'
		new_row['upload_location'] = 'manual'
	else:
		if new_row['state'] == 'EDITED':
			missing = []
			for column in non_null_columns:
				if not new_row[column] or new_row[column] is None:
					missing.append(column)
			if missing:
				return 'Fields {} must be non-null for video to be cut'.format(', '.join(missing)), 400
		elif new_row['state'] != 'UNEDITED':
			return 'Invalid state {}'.format(new_row['state']), 400
		
	new_row['uploader'] = None
	new_row['error'] = None

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
	with database.transaction(conn):
		result = database.query(conn, build_query, id=ident, **new_row)
	if result.rowcount != 1:
		if result.rowcount == 0.:
			with database.transaction(conn):
				check_result = database.query(conn, """
					SELECT id, state
					FROM events
					WHERE id = %s;""", ident)
			current_row = check_result.fetchone()
			if current_row.state not in ['UNEDITED', 'EDITED', 'CLAIMED']:
				return 'Video already published', 403	
		raise Exception('Database consistancy error for id = {}'.format(ident))
			
	logging.info('Row {} updated to state {}'.format(ident, new_row['state']))
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
