
import datetime
import logging
import os
import random
import signal
import traceback

import argh
import gevent.event
from gevent.pool import Pool

from common import database
from common.segments import parse_segment_path, list_segment_files

from .extract import extract_segment, load_prototypes


cli = argh.EntryPoint()


@cli
@argh.named("extract-segment")
def do_extract_segment(*segment_paths, prototypes_path="./prototypes"):
	"""Extract info from individual segments and print them"""
	prototypes = load_prototypes(prototypes_path)
	for segment_path in segment_paths:
		segment_info = parse_segment_path(segment_path)
		odometer, clock, tod = extract_segment(prototypes, segment_info, segment_info.end)
		print(f"{segment_path} {odometer} {clock} {tod}")


@cli
def compare_segments(dbconnect, base_dir='.', prototypes_path="./prototypes", since=None, until=None, num=100, null_chance=0.25, verbose=False):
	"""
	Collect some representitive samples from the database and re-runs them to compare to previous results.
	num is how many samples to try.
	"""
	prototypes = load_prototypes(prototypes_path)
	dbmanager = database.DBManager(dsn=dbconnect)
	conn = dbmanager.get_conn()

	where = []
	if since:
		where.append("timestamp >= %(since)s")
	if until:
		where.append("timestamp < %(until)s")
	if not where:
		where = ["true"]
	where = " AND ".join(where)
	result = database.query(conn, f"""
		SELECT odometer, clock, timeofday, segment
		FROM bus_data
		WHERE segment IS NOT NULL
			AND {where}
	""", since=since, until=until)

	# To get a wider range of tests, pick at random from all unique odo readings
	available = {}
	for row in result.fetchall():
		available.setdefault(row.odometer, []).append((row.segment, row.clock, row.timeofday))

	selected = []
	while available and len(selected) < num:
		if None in available and random.random() < null_chance:
			odometer = None
		else:
			odometer = random.choice(list(available.keys()))
		segments = available[odometer]
		random.shuffle(segments)
		selected.append((odometer, segments.pop()))
		if not segments:
			del available[odometer]

	results = []
	for old_odometer, (segment, old_clock, old_tod) in selected:
		path = os.path.join(base_dir, segment)
		segment_info = parse_segment_path(path)
		odometer, clock, tod = extract_segment(prototypes, segment_info, segment_info.end)
		results.append((segment, {
			"odo": (old_odometer, odometer),
			"clock": (old_clock, clock),
			"tod": (old_tod, tod),
		}))

	matching = 0
	for segment, data in sorted(results, key=lambda t: t[0]):
		matched = True
		for k, (old, new) in data.items():
			match = old == new
			if verbose or not match:
				print(f"{segment} {k}: {old} | {new}")
			matched &= match
		if matched:
			matching += 1

	print("{}/{} matched".format(matching, len(selected)))


@cli
@argh.named("analyze-segment")
def do_analyze_segment(dbconnect, *segment_paths, base_dir='.', prototypes_path="./prototypes"):
	"""Analyze individual segments and write them to the database"""
	prototypes = load_prototypes(prototypes_path)
	dbmanager = database.DBManager(dsn=dbconnect)

	for segment_path in segment_paths:
		analyze_segment(dbmanager, prototypes, segment_path)


def analyze_segment(db_manager, prototypes, segment_path, check_segment_name=None):
	segment_info = parse_segment_path(segment_path)
	if segment_info.type == "temp":
		logging.info("Ignoring temp segment {}".format(segment_path))
		return

	segment_name = '/'.join(segment_path.split('/')[-4:]) # just keep last 4 path parts
	if check_segment_name is not None:
		assert segment_name == check_segment_name

	timestamp = segment_info.end

	try:
		odometer, clock, tod = extract_segment(prototypes, segment_info, timestamp)
	except Exception:
		logging.warning(f"Failed to extract segment {segment_path!r}", exc_info=True)
		odometer = None
		clock = None
		tod = None
		error = traceback.format_exc()
	else:
		logging.info(f"Got odometer = {odometer}, clock = {clock}, time of day = {tod} for segment {segment_path!r}")
		error = None

	conn = db_manager.get_conn()
	database.query(
		conn,
		"""
			INSERT INTO bus_data (channel, timestamp, segment, error, odometer, clock, timeofday)
			VALUES (%(channel)s, %(timestamp)s, %(segment)s, %(error)s, %(odometer)s, %(clock)s, %(timeofday)s)
			ON CONFLICT (channel, timestamp, segment) DO UPDATE
				SET error = %(error)s,
					odometer = %(odometer)s,
					clock = %(clock)s,
					timeofday = %(timeofday)s
		""",
		channel=segment_info.channel,
		timestamp=timestamp,
		segment=segment_name,
		error=error,
		odometer=odometer,
		clock=clock,
		timeofday=tod,
	)
	db_manager.put_conn(conn)


def analyze_hour(db_manager, prototypes, existing_segments, base_dir, channel, quality, hour, concurrency=10):
	hour_path = os.path.join(base_dir, channel, quality, hour)
	segments = sorted(list_segment_files(hour_path))

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
	pool = Pool(concurrency)
	workers = []
	for segment_path, segment_name in segments_to_do:
		workers.append(pool.spawn(analyze_segment, db_manager, prototypes, segment_path, segment_name))
	for worker in workers:
		worker.get() # re-raise errors


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
	prototypes_path="./prototypes",
	concurrency=10,
):
	CHECK_INTERVAL = 0.5

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
				analyze_hour(db_manager, prototypes, existing_segments, base_dir, channel, quality, hour, concurrency=concurrency)

		if run_once:
			logging.info("Requested to only run once, stopping")
			return

		elapsed = (datetime.datetime.utcnow() - start_time).total_seconds()
		remaining = CHECK_INTERVAL - elapsed
		if remaining > 0:
			logging.info(f"Sleeping {remaining} until next check")
			stopping.wait(remaining)

	logging.info("Gracefully stopped")
