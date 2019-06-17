
import json
import logging
import signal

import argh
import gevent.backdoor
import gevent.event
import prometheus_client as prom

import common
from common.database import DBManager

from .sheets import Sheets

@argh.arg('worksheet-names', nargs='+', help="The names of the individual worksheets within the sheet to operate on.")
def main(dbconnect, sheets_creds_file, sheet_id, worksheet_names, metrics_port=8004, backdoor_port=0):
	"""dbconnect should be a postgres connection string, which is either a space-separated
	list of key=value pairs, or a URI like:
		postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE

	sheets_creds_file should be a json file containing keys 'client_id', 'client_secret' and 'refresh_token'.
	"""
	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	stop = gevent.event.Event()
	gevent.signal(signal.SIGTERM, stop.set) # shut down on sigterm

	logging.info("Starting up")

	dbmanager = DBManager(dsn=dbconnect)
	sheets_creds = json.load(open(sheets_creds_file))

	sheets = Sheets(
        client_id=sheets_creds['client_id'],
        client_secret=sheets_creds['client_secret'],
        refresh_token=sheets_creds['refresh_token'],
	)

	# TODO the thing

	logging.info("Gracefully stopped")
