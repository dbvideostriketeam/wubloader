import logging
import os

import argh
from common import dateutil
from common.database import DBManager
from dateutil.parser import ParserError
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


@argh.arg('--host',
          help='Address or socket server will listen to. Default is 0.0.0.0 (everything on the local machine).')
@argh.arg('--port',
          help='Port server will listen on. Default is 8004.')
@argh.arg('--database',
          help='Postgres connection string, which is either a space-separated list of key=value pairs, or a URI like: '
               'postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE')
@argh.arg('--bustime-start',
          help='The start time in UTC for the event, for UTC-Bustime conversion')
def main(database="", host='0.0.0.0', port=8005, bustime_start=None):

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

    logging.info('Starting up')
    server.serve_forever()
    logging.info("Gracefully shut down")
