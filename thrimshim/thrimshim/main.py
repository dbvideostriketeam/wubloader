
import json
import logging

import gevent
import gevent.backdoor
from gevent.pywsgi import WSGIServer
import flask


from common import database
#from stats import stats, after_request

app = flask.Flask('thrimshim')
#app.after_request(after_request)

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

@app.route('/thrimshim/<uuid:key>', methods=['GET', 'POST'])
def thrimshim(key):
	if flask.request.method == 'POST':
		row = flask.request.json
		update_row(row)
	else:

		

def date_handler(obj):
	

def get_row(ident):
	conn = flask.g.db_manager.get_conn()
	with database.transaction(conn):
		result = database.query(conn, 'SELECT * FROM events WHERE id = %s;', ident
	row = results[0]
	assert row.id == ident
	response = row._asdict()
	response = {key:(response[key].isoformat() if isinstance(response[key], datetime.datetime) else response[key]) for key in response.keys()}
	return json.dump(response)


def update_row(ident):


def query_database(ident):

	select start, end, catagory, description, notes, video_title, video_description, video_start, video_end, state, error
	from database where id is ident

def set_row(data):
	to_update = unjson(data)

	update_database(to_update)

def update_database(ident, to_update):

	if state not in ['UNEDITED, EDITED, CLAIMED']:
		return 'Video already published'  

	insert video_title, video_description, video_start, video_end
	#allow_holes, uploader_whitelist, upload_location
	into database where id == indent

	set error to NULL
	set uploader to NULL

	if upload_location:
		set state to 'DONE'

	if publish:
		set state to 'EDITED'
	else:
		set state to 'UNEDITED'
	


def main(host='0.0.0.0', port=8005, connection_string='', backdoor_port=False):

	flask.g.db_manager = database.DBManager(dsn=connection_string)
	server = WSGIServer((host, port), cors(app))

	def stop():
		logging.info("Shutting down")
		server.stop()
	gevent.signal(signal.SIGTERM, stop)

	PromLogCountsHandler.install()
	install_stacksampler()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	logging.info("Starting up")
	server.serve_forever()
	logging.info("Gracefully shut down")
