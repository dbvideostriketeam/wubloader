import logging
import os
from datetime import timedelta, datetime, timezone
from time import sleep

import argh
import common
import gevent
from common import dateutil
from common.database import DBManager
from gevent import signal

from buscribe.buscribe import get_end_of_transcript, transcribe_segments, finish_off_recognizer
from buscribe.recognizer import BuscribeRecognizer


@argh.arg('channel',
          help="Twitch channel to transcribe.")
@argh.arg('--database',
          help='Postgres conection string for database to write transcribed lines to. Either a space-separated list of '
               'key=value pairs, or a URI like: postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE .')
@argh.arg('--model',
          help='Path to STT model files. Defaults to /usr/share/buscribe/vosk-model-en-us-0.21/')
@argh.arg('--spk-model',
          help='Path to speaker recognition model files. Defaults to /usr/share/buscribe/vosk-model-spk-0.4/')
@argh.arg('--start-time',
          help='Start time of the transcript. Buscript will try to start reading 2 min before this time, if available, '
               'to prime the model. The transcripts for that time will not be written to the database. If not given '
               'transcription will start after last already transcribed line.')
@argh.arg('--end-time',
          help='End of transcript. If not given continues to transcribe live.')
@argh.arg('--base-dir',
          help='Directory from which segments will be grabbed. Default is current working directory.')
def main(channel, database="", base_dir=".",
         model="/usr/share/buscribe/vosk-model-en-us-0.21/", spk_model="/usr/share/buscribe/vosk-model-spk-0.4/",
         start_time=None, end_time=None):
    SAMPLE_RATE = 48000
    segments_dir = os.path.join(base_dir, channel, "source")

    logging.debug("Grabbing database...")
    db_manager = DBManager(dsn=database)
    db_conn = db_manager.get_conn()
    db_cursor = db_conn.cursor()
    logging.debug("Got database cursor.")

    logging.info("Figuring out starting time...")
    db_start_time = get_end_of_transcript(db_cursor)

    # Database start time takes priority
    if db_start_time is not None:
        start_time = db_start_time
    elif start_time is not None:
        start_time = dateutil.parse(start_time)
    else:
        # No start time argument AND no end of transcript (empty database)
        logging.error("Couldn't figure out start time!")
        db_conn.close()
        exit(1)

    if end_time is not None:
        end_time = dateutil.parse(end_time)

    logging.info("Loading models...")
    recognizer = BuscribeRecognizer(SAMPLE_RATE, model, spk_model)
    logging.info("Models loaded.")

    logging.info('Transcribing from {}'.format(start_time))

    # Start priming the recognizer if possible
    start_of_transcription = start_time
    start_time -= timedelta(minutes=2)

    stopping = gevent.event.Event()

    def stop():
        logging.info("Shutting down")

        stopping.set()

    gevent.signal_handler(signal.SIGTERM, stop)

    segments_end_time = None

    while start_time < end_time:
        # If end time isn't given, use current time (plus fudge) to get a "live" segment list
        segments = common.get_best_segments(segments_dir,
                                            start_time,
                                            end_time if end_time is not None else
                                            datetime.utcnow() + timedelta(minutes=2))

        # Remove initial None segment (indicating segments start time is after desired start time) if it exists
        if segments[0] is None:
            segments = segments[1:]

        # If there are no segments, we:
        # - reached the live edge, or
        # - reached a still-opening hole
        # In both cases we can wait
        if not segments:
            # If we have waited for more than 1min we flush the pipes to commit the last line of the stream,
            # or commit the last line before a 1min hole.
            if datetime.utcnow() - segments_end_time > timedelta(minutes=1):
                finish_off_recognizer(recognizer, db_cursor)

            logging.info("Waiting for new segments.")
            sleep(30)

            continue  # Retry
        # If there are new segments, but they form a hole (judged somewhat arbitrarily as 2s) relative to
        # segments_end_time, but the hole started less than 1min ago
        elif segments_end_time is not None and \
                segments[0].start - segments_end_time > timedelta(seconds=2) and \
                datetime.utcnow() - segments_end_time < timedelta(minutes=1):

            logging.info("Waiting for segments to be backfilled.")
            sleep(30)

            continue  # Retry

        # If we got new segments, but there was a hole that could not be backfilled
        if segments_end_time is not None and \
                segments[0].start - segments_end_time > timedelta(seconds=2):
            finish_off_recognizer(recognizer, db_cursor)

        # Recognizer is fresh or was reset
        if recognizer.segments_start_time is None:
            recognizer.segments_start_time = segments[0].start
            logging.info(f"Starting from: {segments[0].start}")

        segments_end_time = transcribe_segments(segments, SAMPLE_RATE, recognizer, start_of_transcription, db_cursor,
                                                stopping)

        if end_time is not None and segments_end_time >= end_time or \
                stopping.is_set():
            # Work's done!
            finish_off_recognizer(recognizer, db_cursor)
            db_conn.close()
            exit(0)

        start_time = segments_end_time
