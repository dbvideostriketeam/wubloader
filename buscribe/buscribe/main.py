import logging
import os
from datetime import timedelta, datetime, timezone
from time import sleep

import argh
import common
import gevent
import prometheus_client as prom
from common import dateutil
from common.database import DBManager
from gevent import signal

from buscribe.buscribe import get_end_of_transcript, transcribe_segments, finish_off_recognizer
from buscribe.recognizer import BuscribeRecognizer


buscribe_latest_segment = prom.Gauge(
    "buscribe_latest_segment",
    "Unix timestamp of the end of the last-transcribed segment",
)


@argh.arg('channel',
          help="Twitch channel to transcribe.")
@argh.arg('--database',
          help='Postgres conection string for database to write transcribed lines to. Either a space-separated list of '
               'key=value pairs, or a URI like: postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE .')
@argh.arg('--model',
          help='Path to STT model files. Defaults to /usr/share/buscribe/vosk-model-en-us-0.22/')
@argh.arg('--spk-model',
          help='Path to speaker recognition model files. Defaults to /usr/share/buscribe/vosk-model-spk-0.4/')
@argh.arg('--start-time',
          help='Start time of the transcript. Buscript will try to start reading 2 min before this time, if available, '
               'to prime the model. The transcripts for that time will not be written to the database. If not given '
               'transcription will start after last already transcribed line.')
@argh.arg('--start-time-override',
          help='Ignore database and force override the start time.')
@argh.arg('--end-time',
          help='End of transcript. If not given continues to transcribe live.')
@argh.arg('--base-dir',
          help='Directory from which segments will be grabbed. Default is current working directory.')
def main(channel, database="", base_dir=".",
         model="/usr/share/buscribe/vosk-model-en-us-0.22/", spk_model="/usr/share/buscribe/vosk-model-spk-0.4/",
         start_time=None, end_time=None, start_time_override=None, metrics_port=8009):
    logging.basicConfig(level=os.environ.get('WUBLOADER_LOG_LEVEL', 'INFO').upper())
    common.PromLogCountsHandler.install()
    common.install_stacksampler()
    prom.start_http_server(metrics_port)

    SAMPLE_RATE = 48000
    segments_dir = os.path.join(base_dir, channel, "source")

    logging.debug("Grabbing database...")
    db_manager = DBManager(dsn=database, register_types=False)
    db_conn = db_manager.get_conn()
    db_cursor = db_conn.cursor()
    logging.debug("Got database cursor.")

    logging.info("Figuring out starting time...")
    db_start_time = get_end_of_transcript(db_cursor)

    # ~~Database start time takes priority~~
    # Overrride takes priority
    if start_time_override is not None:
        start_time = dateutil.parse(start_time_override)
    elif db_start_time is not None:
        start_time = db_start_time
    elif start_time is not None:
        start_time = dateutil.parse(start_time)
    else:
        # No start time argument AND no end of transcript (empty database)
        logging.error("Couldn't figure out start time!")
        db_conn.close()
        exit(1)
    logging.info(f"Start time: {start_time}")

    if end_time is not None:
        end_time = dateutil.parse(end_time)

    logging.info(f"End time: {end_time}")

    logging.info("Loading models...")
    recognizer = BuscribeRecognizer(SAMPLE_RATE, model, spk_model)
    logging.info("Models loaded.")

    logging.info(f'Transcribing from {start_time}')

    # Start priming the recognizer if possible
    start_of_transcription = start_time
    start_time -= timedelta(minutes=2)

    stopping = gevent.event.Event()

    def stop():
        logging.info("Shutting down")

        stopping.set()

    gevent.signal_handler(signal.SIGTERM, stop)

    while end_time is None or start_time < end_time:
        buscribe_latest_segment.set((start_time - datetime(1970, 1, 1)).total_seconds())

        # If end time isn't given, use current time (plus fudge) to get a "live" segment list
        segments = common.get_best_segments(segments_dir,
                                            start_time,
                                            end_time if end_time is not None else
                                            datetime.utcnow() + timedelta(minutes=2))

        # If there is a hole at the start of the requested range because
        if segments[0] is None:
            # The hole is older than a minute, therefore
            # - reset recognizer
            # - continue from existing segments
            if datetime.utcnow() - start_time > timedelta(minutes=1):
                finish_off_recognizer(recognizer, db_cursor)

            # If the hole is less than a minute old, or if we don't have new segments: wait for segments
            if datetime.utcnow() - start_time <= timedelta(minutes=1) or \
                    segments == [None]:
                logging.info("Waiting for new or backfilled segments.")
                sleep(30)

                continue  # Retry

        # Remove initial None segment (indicating segments start time is after desired start time) if it exists
        if segments[0] is None:
            segments = segments[1:]

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
