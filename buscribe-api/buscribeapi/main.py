import logging
import os
from time import sleep

import argh
import gevent.event
from common import dateutil
from common.database import DBManager
from dateutil.parser import ParserError
from gevent import signal
from gevent.pywsgi import WSGIServer

from buscribeapi.buscribeapi import app


def cors(app):
    """WSGI middleware that sets CORS headers"""
    HEADERS = [
        ("Access-Control-Allow-Credentials", "false"),
        ("Access-Control-Allow-Headers", "*"),
        ("Access-Control-Allow-Methods", "GET,HEAD"),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Max-Age", "86400"),
    ]

    def handle(environ, start_response):
        def _start_response(status, headers, exc_info=None):
            headers += HEADERS
            return start_response(status, headers, exc_info)

        return app(environ, _start_response)

    return handle


def servelet(server):
    logging.info('Starting WSGI server.')
    server.serve_forever()

@argh.arg('--host',
          help='Address or socket server will listen to. Default is 0.0.0.0 (everything on the local machine).')
@argh.arg('--port',
          help='Port server will listen on.')
@argh.arg('--database',
          help='Postgres connection string, which is either a space-separated list of key=value pairs, or a URI like: '
               'postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE')
@argh.arg('--bustime-start',
          help='The start time in UTC for the event, for UTC-Bustime conversion')
def main(database="", host='0.0.0.0', port=8010, bustime_start=None):
    if bustime_start is None:
        logging.error("Missing --bustime-start!")
        exit(1)

    server = WSGIServer((host, port), cors(app))

    try:
        app.bustime_start = dateutil.parse(bustime_start)
    except ParserError:
        logging.error("Invalid --bustime-start!")
        exit(1)

    app.db_manager = DBManager(dsn=database)

    stopping = gevent.event.Event()

    def stop():
        logging.info("Shutting down")
        stopping.set()

    gevent.signal_handler(signal.SIGTERM, stop)

    serve = gevent.spawn(servelet, server)

    # Wait for either the stop signal or the server to oops out.
    gevent.wait([serve, stopping], count=1)

    server.stop()
    serve.get()  # Wait for server to shut down and/or re-raise if serve_forever() errored

    logging.info("Gracefully shut down")
