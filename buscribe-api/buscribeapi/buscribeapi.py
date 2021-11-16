from datetime import timedelta

import common
import flask as flask
from common import dateutil, database, format_bustime, dt_to_bustime, bustime_to_dt, parse_bustime
from dateutil.parser import ParserError
from flask import request, jsonify, Response, render_template

app = flask.Flask('buscribe')


@app.template_filter()
def convert_vtt_timedelta(delta: timedelta):
    """Converts a timedelta to a VTT compatible format."""
    return f'{delta.days * 24 + delta.seconds // 3600:02}:{(delta.seconds % 3600) // 60:02}:{delta.seconds % 60:02}.{delta.microseconds // 1000:03}'


@app.template_filter()
def create_seconds_timedelta(seconds):
    """Converts a float of seconds to a timedelta."""
    return timedelta(seconds=seconds)


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

    segments = common.get_best_segments(app.segments_dir,
                                        start_time,
                                        end_time)
    segments_start_time = segments[0].start

    results = fetch_lines(db_conn, start_time, end_time)

    return Response(
        render_template("busubs.jinja", results=results, start_time=segments_start_time,
                        duration_extend=timedelta(seconds=0.3)),
        mimetype="text/vtt"
    )


@app.route('/buscribe/json')
def get_json():
    """Searches the line database for *query*, with optional start_time and end_time boundaries.

    Search is done using PostgreSQL websearch_to_tsquery()
    (https://www.postgresql.org/docs/13/functions-textsearch.html)"""

    start_time_string = request.args.get('start_time')
    bus_start_time_string = request.args.get('bus_start_time')
    if start_time_string is not None:
        try:
            start_time = dateutil.parse(start_time_string)
        except ParserError:
            return "Invalid start time!", 400
    elif bus_start_time_string is not None:
        try:
            start_time = bustime_to_dt(app.bustime_start, parse_bustime(bus_start_time_string))
        except ValueError:
            return "Invalid bus end time!", 400
    else:
        start_time = None

    end_time_string = request.args.get('end_time')
    bus_end_time_string = request.args.get('bus_end_time')
    if end_time_string is not None:
        try:
            end_time = dateutil.parse(end_time_string)
        except ParserError:
            return "Invalid end time!", 400
    elif bus_end_time_string is not None:
        try:
            end_time = bustime_to_dt(app.bustime_start, parse_bustime(bus_end_time_string))
        except ValueError:
            return "Invalid bus end time!", 400
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
                     "start_bus_time": format_bustime(dt_to_bustime(app.bustime_start, row.start_time), "second"),
                     "end_time": row.end_time.isoformat(),
                     "end_bus_time": format_bustime(dt_to_bustime(app.bustime_start, row.end_time), "second"),
                     "verifier": row.verifier,
                     "speakers": row.names,
                     "text": row.highlighted_text if row.highlighted_text is not None else ""} for row in results])


def fetch_lines(db_conn, start_time, end_time, ts_query=None, limit=None, offset=None):
    query = "SELECT *" + \
            (
                ",ts_headline(transcription_line, convert_query(%(text_query)s), 'StartSel=''<span class=\"highlight\">'', StopSel=</span>') AS highlighted_text" if ts_query is not None else ",transcription_line AS highlighted_text") + \
            " FROM buscribe_all_transcriptions WHERE start_time >= %(start_time)s AND end_time <= %(end_time)s "

    if ts_query is not None:
        query += "AND (coalesce(transcription_line_ts, ''::tsvector) || coalesce(names_ts, ''::tsvector)) @@ " \
                 "convert_query(%(text_query)s) " \
                 "ORDER BY ts_rank_cd(coalesce(transcription_line_ts, ''::tsvector) || coalesce(names_ts, ''::tsvector), convert_query(%(text_query)s)) DESC, " \
                 "start_time "
    else:
        query += "ORDER BY start_time "

    if limit is not None:
        query += "LIMIT %(limit)s "

    if offset is not None:
        query += "OFFSET %(limit)s "

    query += ";"

    query = f"""
    WITH q AS (
        SELECT convert_query({"%(text_query)s" if ts_query is not None else "NULL"})
    )
    (SELECT *, ts_headline(transcription_line, (SELECT * FROM q),
     'StartSel=''<span class=\"highlight\">'', StopSel=</span>') AS highlighted_text
            FROM buscribe_all_transcriptions2 
            WHERE start_time >= %(start_time)s AND end_time <= %(end_time)s 
            {"AND verified_line_ts @@ (SELECT * FROM q)" if ts_query is not None else ""}
            ORDER BY {"ts_rank_cd(coalesce(transcription_line_ts, ''::tsvector) ||" +
                       "coalesce(names_ts, ''::tsvector), (SELECT * FROM q)) DESC," if ts_query is not None else ""} 
            start_time)
    UNION
    (SELECT *, ts_headline(transcription_line, (SELECT * FROM q),
     'StartSel=''<span class=\"highlight\">'', StopSel=</span>') AS highlighted_text
            FROM buscribe_all_transcriptions2 
            WHERE start_time >= %(start_time)s AND end_time <= %(end_time)s 
            {"AND machine_line_ts @@ (SELECT * FROM q)" if ts_query is not None else ""} 
            ORDER BY {"ts_rank_cd(coalesce(transcription_line_ts, ''::tsvector) ||" +
                      "coalesce(names_ts, ''::tsvector), (SELECT * FROM q)) DESC," if ts_query is not None else ""} 
            start_time)
           """

    return database.query(db_conn, query,
                          start_time=start_time if start_time is not None else '-infinity',
                          end_time=end_time if end_time is not None else 'infinity',
                          text_query=ts_query,
                          limit=limit,
                          offset=offset
                          )
