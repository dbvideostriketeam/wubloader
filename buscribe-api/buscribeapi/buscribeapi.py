import json
from datetime import timedelta

import flask as flask
from common import dateutil, database
from dateutil.parser import ParserError
from flask import request, jsonify, Response, render_template

app = flask.Flask('buscribe')


@app.template_filter()
def convert_vtt_timedelta(delta: timedelta):
    return f'{delta.days * 24 + delta.seconds // 3600:02}:{(delta.seconds % 3600) // 60:02}:{delta.seconds % 60:02}.{delta.microseconds // 1000:03}'


def round_bus_time(delta: timedelta):
    """Round bus time down to the second."""
    return f'{delta.days * 24 + delta.seconds // 3600:02}:{(delta.seconds % 3600) // 60:02}:{delta.seconds % 60:02}'


@app.route('/buscribe/vtt')
def get_vtt():
    """Returns WebVTT subtitle file for the period between start_time and end_time.

    Times are relative to --bustime-start.

    TODO: Figure out proper offsets."""
    try:
        start_time_string = request.args.get('start_time')
        start_time = dateutil.parse(start_time_string)
    except ParserError:
        return "Invalid start time!", 400
    except KeyError:
        return "Missing start time!", 400

    try:
        end_time_string = request.args['end_time']
        end_time = dateutil.parse(end_time_string)
    except ParserError:
        return "Invalid end time!", 400
    except KeyError:
        return "Missing end time!", 400

    db_conn = app.db_manager.get_conn()

    results = fetch_lines(db_conn, start_time, end_time)

    return Response(
        render_template("busubs.jinja", results=results, bustime_start=app.bustime_start,
                        duration_extend=timedelta(seconds=0.3)),
        mimetype="text/vtt"
    )


@app.route('/buscribe/json')
def get_json():
    """Searches the line database for *query*, with optional start_time and end_time boundaries.

    Search is done using PostgreSQL websearch_to_tsquery()
    (https://www.postgresql.org/docs/13/functions-textsearch.html)"""

    start_time_string = request.args.get('start_time')
    if start_time_string is not None:
        try:
            start_time = dateutil.parse(start_time_string)
        except ParserError:
            return "Invalid start time!", 400
    else:
        start_time = None

    end_time_string = request.args.get('end_time')
    if end_time_string is not None:
        try:
            end_time = dateutil.parse(end_time_string)
        except ParserError:
            return "Invalid end time!", 400
    else:
        end_time = None

    # I think websearch_to_tsquery() sanitizes its own input.
    query = request.args.get('query', default=None)

    limit = request.args.get('limit', default=None, type=int)
    offset = request.args.get('offset', default=None, type=int)

    db_conn = app.db_manager.get_conn()

    results = fetch_lines(db_conn, start_time, end_time, query, limit, offset)

    return jsonify([{"id": row.id,
                     "start_time": row.start_time.isoformat(),
                     "start_bus_time": round_bus_time(row.start_time - app.bustime_start),
                     "end_time": row.end_time.isoformat(),
                     "end_bus_time": round_bus_time(row.start_time - app.bustime_start),
                     "verifier": row.verifier,
                     "speakers": row.names,
                     "text": row.transcription_line if row.transcription_line is not None else ""} for row in results])


def fetch_lines(db_conn, start_time, end_time, ts_query=None, limit=None, offset=None):
    query = "SELECT * FROM buscribe_all_transcriptions WHERE start_time > %(start_time)s AND end_time < %(end_time)s "

    if ts_query is not None:
        query += "AND transcription_line_ts @@ " \
                 "(CASE WHEN websearch_to_tsquery(%(text_query)s)::text != '' THEN websearch_to_tsquery(%(text_query)s)::text || ':*' ELSE '' END)::tsquery " \
                 "ORDER BY ts_rank_cd(transcription_line_ts, (CASE WHEN websearch_to_tsquery(%(text_query)s)::text != '' THEN websearch_to_tsquery(%(text_query)s)::text || ':*' ELSE '' END)::tsquery) DESC, " \
                 "start_time "
    else:
        query += "ORDER BY start_time "

    if limit is not None:
        query += "LIMIT %(limit)s "

    if offset is not None:
        query += "OFFSET %(limit)s "

    query += ";"

    return database.query(db_conn, query,
                          start_time=start_time if start_time is not None else '-infinity',
                          end_time=end_time if end_time is not None else 'infinity',
                          text_query=ts_query,
                          limit=limit,
                          offset=offset
                          )
