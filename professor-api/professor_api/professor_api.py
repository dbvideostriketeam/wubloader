import re

import flask
from common import database
from flask import jsonify, request
from psycopg2.extras import execute_values

app = flask.Flask('buscribe')


@app.route('/professor/line/<int:line_id>', methods=["GET"])
def get_line(line_id):
    db_conn = app.db_manager.get_conn()

    line = database.query(db_conn, "SELECT * FROM buscribe_transcriptions WHERE id = %(id)s;", id=line_id).fetchone()

    if line is None:
        return "Line not found.", 404
    else:
        return {"start_time": line.start_time.isoformat(),
                "end_time": line.end_time.isoformat(),
                "line_data": line.transcription_json}


@app.route('/professor/line/<int:line_id>', methods=["POST"])
def update_line(line_id):
    db_conn = app.db_manager.get_conn()

    if "speakers" in request.json and isinstance(request.json["speakers"], list):
        # Simpler than dealing with uniqueness
        database.query(db_conn,
                       "DELETE FROM buscribe_line_speakers WHERE line = %(line_id)s AND verifier = %(verifier)s;",
                       line_id=line_id, verifier=1)
        execute_values(db_conn.cursor(),
                       "INSERT INTO buscribe_line_speakers(line, speaker, verifier) "
                       "VALUES %s;",
                       [(line_id, speaker, 1) for speaker in
                        request.json["speakers"]])
    if "transcription" in request.json and isinstance(request.json["transcription"], str):
        verified_line = request.json["transcription"].lower()
        verified_line = re.sub(r"[^[a-z]\s']]", "", verified_line)

        database.query(db_conn,
                       "DELETE FROM buscribe_verified_lines WHERE line = %(line_id)s AND verifier = %(verifier)s;",
                       line_id=line_id, verifier=1)
        database.query(db_conn,
                       "INSERT INTO buscribe_verified_lines(line, verified_line, verifier) "
                       "VALUES (%(line)s, %(verified_line)s, %(verifier)s)",
                       line=line_id, verified_line=verified_line, verifier=1)

    return "", 204


@app.route('/professor/speaker', methods=["GET"])
def get_speakers():
    db_conn = app.db_manager.get_conn()

    speakers = database.query(db_conn, "SELECT name FROM buscribe_speakers;")

    return jsonify([{"id": speaker.id, "name": speaker.name} for speaker in speakers])


@app.route('/professor/speaker/<int:speaker_id>', methods=["GET"])
def get_speaker(speaker_id):
    db_conn = app.db_manager.get_conn()

    speaker = database.query(db_conn, "SELECT name FROM buscribe_speakers WHERE id = %(id)s;", id=speaker_id).fetchone()

    if speaker is None:
        return "Speaker not found.", 404
    else:
        return jsonify(speaker.name)


@app.route('/professor/speaker', methods=["PUT"])
def new_speaker():
    name = request.json

    if not isinstance(name, str):
        return "Invalid name!", 400

    name = name.lower()
    name = re.sub(r"[^\w\s']", "", name)
    db_conn = app.db_manager.get_conn()

    speakers = database.query(db_conn, "INSERT INTO buscribe_speakers(name) "
                                       "VALUES (%(name)s) "
                                       "ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name "
                                       "RETURNING id;", name=name)

    return "", 200, {"Content-Location": f"/professor/speaker/{speakers.fetchone().id}"}
