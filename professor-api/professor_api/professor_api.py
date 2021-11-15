import re
import urllib.parse
from functools import wraps
from random import randrange

import flask
import gevent
from common import database
from flask import jsonify, request, copy_current_request_context
from gevent import sleep
from psycopg2.extras import execute_values

from google.oauth2 import id_token
from google.auth.transport import requests

app = flask.Flask('buscribe')


def authenticate(f):
    """Authenticate a token against the database.

    Reference: https://developers.google.com/identity/sign-in/web/backend-auth
    https://developers.google.com/identity/gsi/web/guides/verify-google-id-token#using-a-google-api-client-library"""

    @wraps(f)
    def auth_wrapper(*args, **kwargs):

        try:
            user_token = request.cookies.get("credentials")
            print(user_token)
        except (KeyError, TypeError):
            return 'User token required', 401

        try:
            idinfo = id_token.verify_oauth2_token(user_token, requests.Request(),
                                                  "164084252563-kaks3no7muqb82suvbubg7r0o87aip7n.apps.googleusercontent.com")
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                raise ValueError('Wrong issuer.')
        except ValueError:
            return 'Invalid token. Access denied.', 403

        # check whether user is in the database
        email = idinfo['email'].lower()
        conn = app.db_manager.get_conn()
        results = database.query(conn, """
                    SELECT email
                    FROM buscribe_verifiers
                    WHERE lower(email) = %s""", email)
        row = results.fetchone()
        if row is None:
            return 'Unknown user. Access denied.', 403

        return f(*args, editor=email, **kwargs)

    return auth_wrapper


@app.route('/professor/line/<int:line_id>', methods=["GET"])
def get_line(line_id):
    db_conn = app.db_manager.get_conn()

    line = database.query(db_conn, "SELECT * FROM buscribe_transcriptions WHERE id = %(id)s;", id=line_id).fetchone()

    if line is None:
        return "Line not found.", 404
    else:
        return {"id": line.id,
                "start_time": line.start_time.isoformat(),
                "end_time": line.end_time.isoformat(),
                "line_data": line.transcription_json}


@app.route('/professor/line/random', methods=["GET"])
def get_random_line():
    db_conn = app.db_manager.get_conn()

    n_lines = database.query(db_conn, "SELECT count(*) AS n_lines FROM buscribe_transcriptions;").fetchone().n_lines

    row = randrange(n_lines)

    line = database.query(db_conn, "SELECT * FROM buscribe_transcriptions OFFSET %(row)s LIMIT 1;", row=row).fetchone()

    if line is None:
        return "Line not found.", 404
    else:
        return {"id": line.id,
                "start_time": line.start_time.isoformat(),
                "end_time": line.end_time.isoformat(),
                "line_data": line.transcription_json}


@app.route('/professor/line/<int:line_id>/playlist.m3u8', methods=["GET"])
def get_playlist(line_id):
    db_conn = app.db_manager.get_conn()

    line = database.query(db_conn, "SELECT * FROM buscribe_transcriptions WHERE id = %(id)s;", id=line_id).fetchone()

    if line is None:
        return "Line not found.", 404
    else:
        start_time_iso = line.start_time.isoformat()
        end_time_iso = line.end_time.isoformat()
        duration = line.end_time - line.start_time
        return f"""#EXTM3U
#EXT-X-PLAYLIST-TYPE:vod
#EXT-X-TARGETDURATION:{duration.total_seconds()}
#EXT-X-PROGRAM-DATE-TIME:{start_time_iso}
#EXTINF:{duration.total_seconds()}
/cut/desertbus/source.ts?start={urllib.parse.quote_plus(start_time_iso)}&end={urllib.parse.quote_plus(end_time_iso)}&type=rough&allow_holes=true
#EXT-X-ENDLIST"""


@app.route('/professor/line/<int:line_id>', methods=["POST"])
@authenticate
def update_line(line_id, editor):
    db_conn = app.db_manager.get_conn()

    if "speakers" in request.json and \
            isinstance(request.json["speakers"], list) and \
            request.json["speakers"] != []:
        # Simpler than dealing with uniqueness
        database.query(db_conn,
                       "DELETE FROM buscribe_line_speakers WHERE line = %(line_id)s AND verifier = %(verifier)s;",
                       line_id=line_id, verifier=editor)
        execute_values(db_conn.cursor(),
                       "INSERT INTO buscribe_line_speakers(line, speaker, verifier) "
                       "VALUES %s;",
                       [(line_id, speaker, editor) for speaker in
                        request.json["speakers"]])
    if "transcription" in request.json and \
            isinstance(request.json["transcription"], str) and \
            request.json["transcription"] != "":
        verified_line = request.json["transcription"].lower()
        verified_line = re.sub(r"[^[a-z]\s']]", "", verified_line)

        database.query(db_conn,
                       "DELETE FROM buscribe_verified_lines WHERE line = %(line_id)s AND verifier = %(verifier)s;",
                       line_id=line_id, verifier=editor)
        database.query(db_conn,
                       "INSERT INTO buscribe_verified_lines(line, verified_line, verifier) "
                       "VALUES (%(line)s, %(verified_line)s, %(verifier)s)",
                       line=line_id, verified_line=verified_line, verifier=editor)

    return "", 204


@app.route('/professor/speaker', methods=["GET"])
def get_speakers():
    db_conn = app.db_manager.get_conn()

    speakers = database.query(db_conn, "SELECT id, name FROM buscribe_speakers;")

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
@authenticate
def new_speaker(editor=None):
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
