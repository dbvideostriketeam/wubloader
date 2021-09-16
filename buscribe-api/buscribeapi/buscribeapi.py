import flask as flask
from common import dateutil
from dateutil.parser import ParserError
from flask import request

app = flask.Flask('buscribe')


@app.route('/buscribe/vtt')
def get_vtt():
    """Returns WebVTT subtitle file for the period between start_time and end_time."""
    try:
        start_time_string = request.args.get('start_time')
        start_time = dateutil.parse(start_time_string)
    except ParserError:
        return "Invalid start time!", 400
    except ValueError:
        return "Missing start time!", 400

    try:
        end_time_string = request.args.get('end_time')
        end_time = dateutil.parse(end_time_string)
    except ParserError:
        return "Invalid end time!", 400
    except ValueError:
        return "Missing end time!", 400


@app.route('/buscribe/json')
def get_json():
    """Searches the line database for *query*, with optional start_time and end_time boundaries.

    Search is done using PostgreSQL websearch_to_tsquery() (https://www.postgresql.org/docs/13/functions-textsearch.html)"""
    start_time_string = request.args.get('start_time')
    try:
        start_time = dateutil.parse(start_time_string)
    except ParserError:
        return "Invalid start time!", 400

    end_time_string = request.args.get('end_time', default=None)
    try:
        end_time = dateutil.parse(end_time_string)
    except ParserError:
        return "Invalid end time!", 400

    # I think websearch_to_tsquery() sanitizes its own input.
    query = request.args.get('end_time', default=None)
