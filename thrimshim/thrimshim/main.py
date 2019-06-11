import datetime
import json
import logging
import signal

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


@app.route('/thrimshim/<uuid:ident>', methods=['GET', 'POST'])
def thrimshim(ident):
	"""Comunicate between Thrimbletrimmer and the Wubloader database."""
	ident = str(ident)
	if flask.request.method == 'POST':
		row = flask.request.json
		return update_row(ident, row)

	else:
		return get_row(ident)
		
		
def get_row(ident):
	"""Gets the row from the database with id == ident."""
	conn = app.db_manager.get_conn()
	with database.transaction(conn):
		results = database.query(conn, """
			SELECT *
			FROM events
			WHERE id = %s;""", ident)
	row = results.fetchone()
	if row is None:
		return 'Row {} not found'.format(ident), 404
	assert row.id == ident
	response = row._asdict()
	response = {key:(response[key].isoformat() if isinstance(response[key], datetime.datetime) else response[key]) for key in response.keys()}
	return json.dumps(response)



def update_row(ident, new_row):
	"""Updates row of database with id == ident with the edit columns in
	new_row.

	If a 'video_link' is provided in uodate, interperate this as a manual video
	upload and set state to 'DONE'"""

	edit_columns = ['allow_holes', 'uploader_whitelist', 'upload_location',
				'video_start', 'video_end', 'video_title', 'video_description',
				'video_channel', 'video_quality']

	row_keys = new_row.keys()
	for column in edit_columns + ['state']:
		if column not in row_keys:
			return 'Missing {} from JSON'.format(column), 400

	state_columns = ['state', 'uploader', 'error', 'video_link'] 

	conn = app.db_manager.get_conn()
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
		return 'Video already published', 400


	if 'video_link' in new_row and new_row['video_link']:
		new_row['state'] = 'DONE'
		new_row['upload_location'] = 'manual'
	else:
		new_row['video_link'] = None
		if new_row['state'] not in ['EDITED']:
			new_row['state'] = 'UNEDITED'

	new_row['uploader'] = None
	new_row['error'] = None

	columns = edit_columns + state_columns
	build_query = sql.SQL("""
		UPDATE events
		set {}
		WHERE id = %(id)s""").format(sql.SQL(", ").join(
			sql.SQL("{} = {}").format(
				sql.Identifier(column), sql.Placeholder(column),
			) for column in columns
		))
	kwargs = {column:new_row[column] for column in columns}
	kwargs['id'] = ident
	with database.transaction(conn):
		result = database.query(conn, build_query, **kwargs)
	if result.rowcount != 1:
		raise Exception('No row with id {} to update'.format(ident))
			
	logging.info('Row {} updated to state {}'.format(ident, new_row['state']))
	return 'Row updated'


def main(host='0.0.0.0', port=8004, connection_string='', backdoor_port=0):

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
