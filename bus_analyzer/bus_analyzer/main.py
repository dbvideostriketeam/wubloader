
import datetime
import logging
import os
import signal
import traceback

import argh
import gevent.event

from common import database
from common.segments import parse_segment_path

from .extract import extract_segment, load_prototypes


cli = argh.EntryPoint()


@cli
@argh.named("extract-segment")
def do_extract_segment(*segment_paths, prototypes_path="./odo-digit-prototypes"):
	"""Extract info from individual segments and print them"""
	prototypes = load_prototypes(prototypes_path)
	for segment_path in segment_paths:
		segment_info = parse_segment_path(segment_path)
		odometer = extract_segment(prototypes, segment_info)
		print(f"{segment_path} {odometer}")


@cli
@argh.named("analyze-segment")
def do_analyze_segment(dbconnect, *segment_paths, base_dir='.', prototypes_path="./odo-digit-prototypes"):
	"""Analyze individual segments and write them to the database"""
	prototypes = load_prototypes(prototypes_path)
	dbmanager = database.DBManager(dsn=dbconnect)
	conn = dbmanager.get_conn()

	for segment_path in segment_paths:
		analyze_segment(conn, prototypes, segment_path)


def analyze_segment(conn, prototypes, segment_path, check_segment_name=None):
	segment_info = parse_segment_path(segment_path)
	if segment_info.type == "temp":
		logging.info("Ignoring temp segment {}".format(segment_path))
		return

	segment_name = '/'.join(segment_path.split('/')[-4:]) # just keep last 4 path parts
	if check_segment_name is not None:
		assert segment_name == check_segment_name

	try:
		odometer = extract_segment(prototypes, segment_info)
	except Exception:
		logging.warning(f"Failed to extract segment {segment_path!r}", exc_info=True)
		odometer = None
		error = traceback.format_exc()
	else:
		logging.info(f"Got odometer = {odometer} for segment {segment_path!r}")
		error = None

	database.query(
		conn,
		"""
			INSERT INTO bus_data (channel, timestamp, segment, error, odometer)
			VALUES (%(channel)s, %(timestamp)s, %(segment)s, %(error)s, %(odometer)s)
			ON CONFLICT (channel, timestamp, segment) DO UPDATE
				SET error = %(error)s,
					odometer = %(odometer)s
		""",
		channel=segment_info.channel,
		timestamp=segment_info.start,
		segment=segment_name,
		error=error,
		odometer=odometer,
	)


def analyze_hour(conn, prototypes, existing_segments, base_dir, channel, quality, hour):
	hour_path = os.path.join(base_dir, channel, quality, hour)
	try:
		segments = os.listdir(hour_path)
	except FileNotFoundError:
		logging.info(f"No such hour {hour_path!r}, skipping")
		return

	logging.info("Found {} segments for hour {!r}".format(len(segments), hour_path))
	segments_to_do = []
	for segment in segments:
		# Format as relative path from basedir, this is the format the DB expects.
		segment_name = os.path.join(channel, quality, hour, segment)
		if segment_name in existing_segments:
			continue

		segment_path = os.path.join(base_dir, segment_name)
		assert segment_path == os.path.join(hour_path, segment)

		segments_to_do.append((segment_path, segment_name))

	logging.info("Found {} segments not already existing".format(len(segments_to_do)))
	for segment_path, segment_name in segments_to_do:
		analyze_segment(conn, prototypes, segment_path, segment_name)


def parse_hours(s):
	try:
		return int(s)
	except ValueError:
		return s.split(",")


@cli
@argh.arg("--hours", type=parse_hours, help="If integer, watch the most recent N hours. Otherwise, comma-seperated list of hours.")
@argh.arg("channels", nargs="+")
def main(
	dbconnect,
	*channels,
	base_dir='.',
	quality='source',
	hours=2,
	run_once=False,
	overwrite=False,
	prototypes_path="./odo-digit-prototypes",
):
	CHECK_INTERVAL = 2

	stopping = gevent.event.Event()

	gevent.signal_handler(signal.SIGTERM, stopping.set)

	db_manager = database.DBManager(dsn=dbconnect)
	conn = db_manager.get_conn()

	prototypes = load_prototypes(prototypes_path)

	logging.info("Started")

	while not stopping.is_set():
		start_time = datetime.datetime.utcnow()

		# If we aren't using a hard-coded hours list, work out hours based on current time
		if isinstance(hours, int):
			do_hours = [
				(start_time - datetime.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H")
				for hours_ago in range(hours)
			]
		else:
			do_hours = hours

		# Unless we're overwriting, fetch a list of existing segments from the database.
		# We can optimize a little here by restricting to the channels and hour range we need.
		if overwrite:
			existing_segments = set()
		else:
			start = datetime.datetime.strptime(min(do_hours), "%Y-%m-%dT%H")
			end = datetime.datetime.strptime(max(do_hours), "%Y-%m-%dT%H")
			logging.info("Fetching existing segments from {} to {} for {}".format(
				start,
				end,
				", ".join(channels),
			))
			result = database.query(conn, """
				SELECT segment
				FROM bus_data
				WHERE channel IN %(channels)s
					AND timestamp >= %(start)s::timestamp
					AND timestamp < %(end)s::timestamp + interval '1 hour'
					AND segment IS NOT NULL
			""", channels=channels, start=start, end=end)
			existing_segments = {segment for (segment,) in result.fetchall()}
			logging.info("Found {} existing segments".format(len(existing_segments)))

		for channel in channels:
			for hour in do_hours:
				analyze_hour(conn, prototypes, existing_segments, base_dir, channel, quality, hour)

		if run_once:
			logging.info("Requested to only run once, stopping")
			return

		elapsed = (datetime.datetime.utcnow() - start_time).total_seconds()
		remaining = CHECK_INTERVAL - elapsed
		if remaining > 0:
			logging.info(f"Sleeping {remaining} until next check")
			stopping.wait(remaining)

	logging.info("Gracefully stopped")
