
import datetime
import logging
import os
import random
import signal
import time
import traceback

import argh
import gevent.event
from gevent.pool import Pool
import prometheus_client as prom

import common
from common import database
from common.segments import parse_segment_path, list_segment_files
from common.stats import timed

from .extract import extract_segment, load_prototypes
from .post_processing import post_process_miles, post_process_clocks

cli = argh.EntryPoint()

segment_analyzed_duration = prom.Histogram(
	'segments_analyzed',
	'Number of segments succesfully analyzed',
	['channel', 'quality', 'error'],
)

latest_analyzed_timestamp = None
latest_analyzed_segment_time = prom.Gauge(
	'latest_analyzed_segment_time',
	'The timestamp of the segment with the latest timestamp seen so far. Can be used to estimate lag behind live data.',
	['channel', 'quality'],
)

latest_analyzed_segment_odometer = prom.Gauge(
	'latest_analyzed_segment_odometer',
	'The odometer value of the segment with the latest timestamp seen so far. Mostly just for fun so we kind of have this value over time in prometheus.',
	['channel', 'quality'],
)

latest_analyzed_segment_clock = prom.Gauge(
	'latest_analyzed_segment_clock',
	'The clock value of the segment with the latest timestamp seen so far. Mostly just for fun so we kind of have this value over time in prometheus.',
	['channel', 'quality'],
)

@cli
@argh.named("extract-segment")
def do_extract_segment(*segment_paths, prototypes_path="./prototypes", profile='DBfH_2025'):
	"""Extract info from individual segments and print them"""
	prototypes = load_prototypes(prototypes_path)
	for segment_path in segment_paths:
		segment_info = parse_segment_path(segment_path)
		odometer, clock, tod = extract_segment(prototypes, segment_info, segment_info.start, profile)
		print(f"{segment_path} {odometer} {clock} {tod}")


@cli
def compare_segments(dbconnect, base_dir='.', prototypes_path="./prototypes", since=None, until=None, num=100, null_chance=0.25, profile='DBfH_2025', verbose=False):
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
		SELECT raw_odometer, raw_clock, timeofday, segment
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
		odometer, clock, tod = extract_segment(prototypes, segment_info, segment_info.start, profile)
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
def do_analyze_segment(dbconnect, *segment_paths, base_dir='.', prototypes_path="./prototypes", profile='DBfH_2025'):
	"""Analyze individual segments and write them to the database"""
	prototypes = load_prototypes(prototypes_path)
	dbmanager = database.DBManager(dsn=dbconnect)

	for segment_path in segment_paths:
		analyze_segment(dbmanager, prototypes, segment_path, profile)


def analyze_segment(db_manager, prototypes, segment_path, profile, check_segment_name=None):
	segment_info = parse_segment_path(segment_path)
	if segment_info.type == "temp":
		logging.info("Ignoring temp segment {}".format(segment_path))
		return

	segment_name = '/'.join(segment_path.split('/')[-4:]) # just keep last 4 path parts
	if check_segment_name is not None:
		assert segment_name == check_segment_name

	# A timestamp fully at the end doesn't get us a valid frame.
	# But we want to be as late as possible to minimize latency.
	# We attempt to do a fixed time before the end, or use the start if too short.
	timestamp = max(segment_info.start, segment_info.end - datetime.timedelta(seconds=0.1))

	start = time.monotonic()
	try:
		odometer, clock, tod = extract_segment(prototypes, segment_info, timestamp, profile)
	except Exception:
		logging.warning(f"Failed to extract segment {segment_path!r}", exc_info=True)
		odometer = None
		clock = None
		tod = None
		error = traceback.format_exc()
	else:
		logging.info(f"Got odometer = {odometer}, clock = {clock}, time of day = {tod} for segment {segment_path!r}")
		error = None
		global latest_analyzed_timestamp
		if latest_analyzed_timestamp is None or latest_analyzed_timestamp < timestamp:
			labels = segment_info.channel, segment_info.quality
			latest_analyzed_segment_time.labels(*labels).set((timestamp - datetime.datetime(1970, 1, 1)).total_seconds())
			if odometer is not None:
				latest_analyzed_segment_odometer.labels(*labels).set(odometer)
			if clock is not None:
				latest_analyzed_segment_clock.labels(*labels).set(clock)
			latest_analyzed_timestamp = timestamp
	segment_analyzed_duration.labels(channel=segment_info.channel, quality=segment_info.quality, error=(error is not None)).observe(time.monotonic() - start)

	conn = db_manager.get_conn()
	database.query(
		conn,
		"""
			INSERT INTO bus_data (channel, timestamp, segment, error, raw_odometer, raw_clock, timeofday)
			VALUES (%(channel)s, %(timestamp)s, %(segment)s, %(error)s, %(odometer)s, %(clock)s, %(timeofday)s)
			ON CONFLICT (channel, timestamp, segment) DO UPDATE
				SET error = %(error)s,
					raw_odometer = %(odometer)s,
					raw_clock = %(clock)s,
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


def analyze_hour(db_manager, prototypes, existing_segments, base_dir, channel, quality, hour, profile, concurrency=10):
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
		workers.append(pool.spawn(analyze_segment, db_manager, prototypes, segment_path, profile, segment_name))
	for worker in workers:
		worker.get() # re-raise errors

	return [segment[1] for segment in segments_to_do]

@timed(normalize=lambda result, db_manager, segments, channel: len(segments))
def post_process(db_manager, segments, channel):

	if segments:
		segments = sorted(segments)
		start = parse_segment_path(segments[0]).start
		a_minute_ago = start - datetime.timedelta(minutes=1)
		start = start - datetime.timedelta(minutes=30)
		end = parse_segment_path(segments[-1]).end
	# if no list of segments, post process all segments
	elif segments is None:
		start = datetime.datetime(1, 1, 1)
		a_minute_ago = start
		end = datetime.datetime.now(datetime.UTC)
	else:
		logging.info('No segments to post process')
		return

	conn = db_manager.get_conn()
	query = database.query(conn, """
		SELECT segment, timestamp, raw_odometer, raw_clock, timeofday, odometer, clock
		FROM bus_data
		WHERE channel = %(channel)s
			AND timestamp > %(start)s
			AND timestamp < %(end)s
		--AND NOT segment LIKE '%%partial%%'
		ORDER BY timestamp;
		""", start=start, end=end, channel=channel)
	rows = query.fetchall()
	segments, times, miles, clocks, days, old_miles, old_clocks = zip(*rows)
	logging.info('{} segments fetched for post processing between {} and {}'.format(len(times), times[0], times[-1]))

	for index in range(len(times) - 1, 0, -1):
		if times[index] <= a_minute_ago:
			break
	seconds = [(time - times[0]).total_seconds() for time in times]
	corrected_miles = post_process_miles(seconds[index:], miles[index:], days[index:])
	corrected_clocks = post_process_clocks(seconds, clocks, days)[index:]
	old_miles = old_miles[index:]
	old_clocks = old_clocks[index:]
	segments = segments[index:]

	count = 0
	for i in range(len(corrected_miles)):
		if corrected_miles[i] == old_miles[i] and corrected_clocks[i] == old_clocks[i]:
			continue
		query = database.query(conn, """
			UPDATE bus_data
			SET odometer = %(odometer)s, clock = %(clock)s
			WHERE channel = %(channel)s AND segment = %(segment)s AND timestamp = %(timestamp)s
		""", channel=channel, segment=segments[i], timestamp=times[i], odometer=corrected_miles[i], clock=corrected_clocks[i])
		count += 1
	
	logging.info("{} segments post processed with {} segments updated".format(len(corrected_clocks), count))
	

def parse_hours(s):
	try:
		return int(s)
	except ValueError:
		return s.split(",")


@cli
@argh.arg('dbconnect', help='Database connection string.')
@argh.arg("channels", nargs="+", help='List of channels to analyze.')
@argh.arg('--base-dir', help='Directory of segments to be analyzed. Default is current working directory')
@argh.arg('--quality', help='Quality to analyze. Default source.')
@argh.arg("--hours", type=parse_hours, help="If integer, watch the most recent N hours. Otherwise, comma-seperated list of hours.")
@argh.arg('--run-once', help='If True, run analyzing once then exit. Default is False.')
@argh.arg('--overwrite', help='If True, redo analysis for segments already in database. Default is False.')
@argh.arg('--process', help='Post-process analyzed segments. Default is False.')
@argh.arg('--reprocess', help='Repeat post processing. Default is False.')
@argh.arg('--prototypes-path', help="Path to prototype digit images. Default is './prototypes'.")
@argh.arg('--profile', help="Extraction parameters profile to use. Default is 'DBfH_2025'.")
@argh.arg('--concurrency', help='Number of segments to try to analyze simultaneously. Default is 10.')
@argh.arg('--metrics-port', help='Port for Prometheus stats. Default is 8011.')
def main(
	dbconnect,
	*channels,
	base_dir='.',
	quality='source',
	hours=2,
	run_once=False,
	overwrite=False,
	process=False,
	reprocess=False,
	prototypes_path="./prototypes",
	profile='DBfH_2025',
	concurrency=10,
	metrics_port=8011,
):
	CHECK_INTERVAL = 0.5

	stopping = gevent.event.Event()

	gevent.signal_handler(signal.SIGTERM, stopping.set)

	db_manager = database.DBManager(dsn=dbconnect)
	conn = db_manager.get_conn()

	prototypes = load_prototypes(prototypes_path)

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	logging.info("Started analyzing {} with {} as quality over {} hours".format(', '.join(channels), quality, hours))

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
			segments = []
			for hour in do_hours:
				segments += analyze_hour(db_manager, prototypes, existing_segments, base_dir, channel, quality, hour, profile, concurrency=concurrency)
			if reprocess:
				segments = None
			if process:
				try:
					post_process(db_manager, segments, channel)
				except Exception:
					logging.exception("Failed to post-process segments", exc_info=True)

		if run_once:
			logging.info("Requested to only run once, stopping")
			return

		elapsed = (datetime.datetime.utcnow() - start_time).total_seconds()
		remaining = CHECK_INTERVAL - elapsed
		if remaining > 0:
			logging.info(f"Sleeping {remaining} until next check")
			stopping.wait(remaining)

	logging.info("Gracefully stopped")
