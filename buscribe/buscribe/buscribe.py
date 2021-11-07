import json
import logging
import subprocess
from datetime import timedelta, datetime

from gevent.event import Event
from psycopg2._psycopg import cursor

from buscribe.recognizer import BuscribeRecognizer


class HitMissingSegment(Exception):
    pass


def transcribe_segments(segments: list, sample_rate: int, recognizer: BuscribeRecognizer, start_of_transcript: datetime,
                        db_cursor: cursor, stopping: Event):
    """Starts transcribing from a list of segments.

    Only starts committing new lines to the database after reaching start_of_transcript.

    The recognizer must be initialized to sample_rate and have start time set.

    Returns the end time of the last transcribed line."""

    segments_end_time = segments[0].start

    for segment in segments:

        if segment is None:
            return segments_end_time

        segments_end_time += segment.duration

        process = subprocess.Popen(['ffmpeg',
                                    '-loglevel', 'quiet',
                                    '-i', segment.path,
                                    '-ar', str(sample_rate),
                                    '-ac', '1',  # TODO: Check for advanced downmixing
                                    '-f', 's16le', '-'],
                                   stdout=subprocess.PIPE)
        while True:
            data = process.stdout.read(16000)
            if len(data) == 0:
                break
            if recognizer.accept_waveform(data):
                result_json = json.loads(recognizer.result())
                logging.debug(json.dumps(result_json, indent=2))

                if result_json["text"] == "":
                    continue

                line_start_time = recognizer.segments_start_time + timedelta(seconds=result_json["result"][0]["start"])
                line_end_time = recognizer.segments_start_time + timedelta(seconds=result_json["result"][-1]["end"])

                if line_start_time > start_of_transcript:
                    write_line(result_json, line_start_time, line_end_time, db_cursor)

        if stopping.is_set():
            return segments_end_time

    return segments_end_time


def write_line(line_json: dict, line_start_time: datetime, line_end_time: datetime, db_cursor):
    """Commits line to the database"""
    db_cursor.execute(
        "INSERT INTO buscribe_transcriptions("
        "start_time, "
        "end_time, "
        "transcription_line, "
        "line_speaker, "
        "transcription_json) VALUES (%s, %s ,%s, %s, %s)",
        (line_start_time,
         line_end_time,
         line_json["text"],
         line_json["spk"] if "spk" in line_json else None,
         json.dumps(line_json)
         )
    )


def get_end_of_transcript(db_cursor):
    """Grab the end timestamp of the current transcript.

    If there is no existing transcript returns default; used for cold starts."""
    db_cursor.execute("SELECT end_time FROM buscribe.public.buscribe_transcriptions ORDER BY end_time DESC LIMIT 1")
    end_of_transcript_row = db_cursor.fetchone()

    return end_of_transcript_row.end_time if end_of_transcript_row is not None else None


def finish_off_recognizer(recognizer: BuscribeRecognizer, db_cursor):
    """Flush the recognizer, commit the final line to the database and reset it."""
    final_result_json = json.loads(recognizer.final_result())  # Flush the tubes

    if "result" in final_result_json:
        line_start_time = recognizer.segments_start_time + timedelta(seconds=final_result_json["result"][0]["start"])
        line_end_time = recognizer.segments_start_time + timedelta(seconds=final_result_json["result"][-1]["end"])

        write_line(final_result_json, line_start_time, line_end_time, db_cursor)

    recognizer.reset()
