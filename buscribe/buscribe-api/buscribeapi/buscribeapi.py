
import flask as flask
from common import dateutil, database, format_bustime, dt_to_bustime, bustime_to_dt, parse_bustime
from dateutil.parser import ParserError
from flask import request, jsonify

app = flask.Flask('buscribe')


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
    query = f"""
    WITH q AS (
    SELECT convert_query(%(text_query)s)
),
     time_window AS (
         SELECT id
         FROM buscribe_transcriptions
         WHERE start_time >= %(start_time)s
           AND end_time <= %(end_time)s
     ),
     relevant_lines AS (
         (
             SELECT id
             FROM buscribe_transcriptions
             WHERE id IN (SELECT id FROM time_window)
               {"AND to_tsvector('english', transcription_line) @@ (SELECT * FROM q)" if ts_query else ""}
         )
         UNION
         (
             SELECT line
             FROM buscribe_verified_lines
             WHERE line IN (SELECT id FROM time_window)
               {"AND to_tsvector('english', verified_line) @@ (SELECT * FROM q)" if ts_query else ""}
         )
         UNION
         (
             SELECT line
             FROM buscribe_line_speakers
                      INNER JOIN buscribe_speakers ON buscribe_line_speakers.speaker = buscribe_speakers.id
             WHERE line IN (SELECT id FROM time_window)
               {"AND to_tsvector(name) @@ (SELECT * FROM q)" if ts_query else ""}
         )
         UNION
         (
             SELECT line
             FROM buscribe_line_inferred_speakers
                      INNER JOIN buscribe_speakers ON buscribe_line_inferred_speakers.speaker = buscribe_speakers.id
             WHERE line IN (SELECT id FROM time_window)
               {"AND to_tsvector(name) @@ (SELECT * FROM q)" if ts_query else ""}
         )
     )
    (
        (SELECT id,
                start_time,
                end_time,
                null                                                               AS verifier,
                names,
                transcription_line,
                ts_rank_cd(coalesce(to_tsvector('english', transcription_line), ''::tsvector) ||
                           coalesce(to_tsvector(array_to_string(names, ' ')), ''::tsvector), (SELECT * FROM q)) AS rank,
                ts_headline(transcription_line, 
                    (SELECT * FROM q), 'StartSel=''<span class=\"highlight\">'', StopSel=</span>') AS highlighted_text,
                transcription_json
         FROM buscribe_transcriptions
                  LEFT OUTER JOIN (SELECT line, array_agg(name) AS names
                                   FROM buscribe_line_inferred_speakers
                                            INNER JOIN buscribe_speakers
                                                       ON buscribe_line_inferred_speakers.speaker = buscribe_speakers.id
                                   GROUP BY line) AS inferred_speakers ON id = inferred_speakers.line
         WHERE id IN (SELECT id FROM relevant_lines)
        )
        UNION
        (
            SELECT buscribe_transcriptions.id                           AS id,
                   start_time,
                   end_time,
                   cverifier                                            AS verifier,
                   names,
                   coalesce(verifications.verified_line,
                            buscribe_transcriptions.transcription_line) AS transcription_line,
                   ts_rank_cd(coalesce(
                                      setweight(to_tsvector('english', verified_line), 'C'),
                                      to_tsvector('english', buscribe_transcriptions.transcription_line),
                                      ''::tsvector) ||
                              coalesce(setweight(to_tsvector(array_to_string(names, ' ')), 'C'), ''::tsvector),
                              (SELECT * FROM q))                        AS rank,
                   ts_headline(coalesce(verifications.verified_line, buscribe_transcriptions.transcription_line), 
                    (SELECT * FROM q), 'StartSel=''<span class=\"highlight\">'', StopSel=</span>') AS highlighted_text,
                   null                                                 AS transcription_json
            FROM buscribe_transcriptions
                     INNER JOIN (
                SELECT *,
                       coalesce(relevant_verified.line, relevant_speakers.line)         AS cline,
                       coalesce(relevant_verified.verifier, relevant_speakers.verifier) AS cverifier
                FROM (SELECT *
                      FROM buscribe_verified_lines
                      WHERE line IN (SELECT id FROM relevant_lines)) AS relevant_verified
                         FULL OUTER JOIN
                     (SELECT line, verifier, array_agg(name) AS names
                      FROM buscribe_line_speakers
                               INNER JOIN buscribe_speakers
                                          ON buscribe_line_speakers.speaker = buscribe_speakers.id
                      WHERE line IN (SELECT id FROM relevant_lines)
                      GROUP BY line, verifier) AS relevant_speakers
                     ON relevant_verified.line = relevant_speakers.line AND
                        relevant_speakers.verifier = relevant_verified.verifier) AS verifications
                                ON id = verifications.cline
        )
    )
        ORDER BY
            {"rank DESC," if ts_query is not None else ""}
            start_time
        {"OFFSET %(offset)s" if offset is not None else ""}
        {"LIMIT %(limit)s" if limit is not None else ""};
    """

    return database.query(db_conn, query,
                          start_time=start_time if start_time is not None else '-infinity',
                          end_time=end_time if end_time is not None else 'infinity',
                          text_query=ts_query,
                          limit=limit,
                          offset=offset
                          )
