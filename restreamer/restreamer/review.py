
import datetime
import logging
import os
import subprocess
from urlparse import urlparse

import mysql.connector

from common.segments import get_best_segments, full_cut_segments



class NoSegments(Exception):
	pass


class RaceNotFound(Exception):
	pass


class CantFindStart(Exception):
	def __init__(self, racer, found):
		self.racer = racer
		self.found = found
	def __str__(self):
		if self.found > 0:
			return "Found multiple ({}) possible start points for {}".format(self.found, self.racer)
		else:
			return "Failed to find start point for {}".format(self.racer)


def ts(dt):
	return dt.strftime("%FT%T")


def cut_to_file(logger, filename, base_dir, stream, start, end, variant='source', frame_counter=False):
	logger.info("Cutting {}".format(filename))
	segments = get_best_segments(
		os.path.join(base_dir, stream, variant).lower(),
		start, end,
	)
	if None in segments:
		logger.warning("Cutting {} ({} to {}) but it contains holes".format(filename, ts(start), ts(end)))
	if not segments or set(segments) == {None}:
		raise NoSegments("Can't cut {} ({} to {}): No segments".format(filename, ts(start), ts(end)))
	filter_args = []
	# standardize resolution
	filter_args += ["-vf", "scale=-2:720"]
	if frame_counter:
		filter_args += [
			"-vf", "scale=-2:480, drawtext="
				"fontfile=DejaVuSansMono.ttf"
				":fontcolor=white"
				":text='%{e\:t}'"
				":x=(w-tw)/2+100"
				":y=h-(2*lh)",
		]
	encoding_args = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-f', 'mp4']
	with open(filename, 'w') as f:
		for chunk in full_cut_segments(segments, start, end, filter_args + encoding_args):
			f.write(chunk)


def add_range(base, range):
	return [base + datetime.timedelta(seconds=n) for n in range]


def conn_from_url(url):
	args = urlparse(url)
	return mysql.connector.connect(
		user=args.username,
		password=args.password,
		host=args.hostname,
		database=args.path.lstrip('/'),
	)


def review(match_id, race_number, base_dir, db_url, start_range=(0, 5), finish_range=(-5, 10)):
	logger = logging.getLogger("review").getChild("{}-{}".format(match_id, race_number))

	conn = conn_from_url(db_url)
	cur = conn.cursor()
	cur.execute("""
		SELECT
			match_info.racer_1_name as racer_1,
			match_info.racer_2_name as racer_2,
			races.timestamp as start,
			race_runs.time as duration
		FROM match_info
		JOIN match_races ON (match_info.match_id = match_races.match_id)
		JOIN races ON (match_races.race_id = races.race_id)
		JOIN race_runs ON (races.race_id = race_runs.race_id)
		WHERE race_runs.rank = 1
			AND match_info.match_id = %(match_id)s
			AND match_races.race_number = %(race_number)s
	""", {'match_id': match_id, 'race_number': race_number})


	data = cur.fetchall()
	data = [
		[item.encode('utf-8') if isinstance(item, unicode) else item for item in row]
		for row in data
	]

	if not data:
		raise RaceNotFound("Could not find race number {} of match {}".format(match_id, race_number))
	assert len(data) == 1, repr(data)

	(racer1, racer2, start, duration), = data
	end = start + datetime.timedelta(seconds=duration/100.)

	output_name = "{}-{}-{}-{}".format(match_id, racer1, racer2, race_number)
	output_dir = os.path.join(base_dir, "reviews", output_name)
	result_name = "review.{}.{}.mp4".format(*finish_range)
	result_path = os.path.join(output_dir, result_name)
	if os.path.exists(result_path):
		logger.info("Result already exists for {}, reusing".format(result_path))
		return result_path

	finish_paths = []

	for racer_number, racer in enumerate((racer1, racer2)):
		start_path = os.path.join(output_dir, "start-{}.mp4".format(racer_number))

		logger.info("Cutting start for racer {} ({})".format(racer_number, racer))
		start_start, start_end = add_range(start, start_range)
		cut_to_file(logger, start_path, base_dir, racer, start_start, start_end)

		logger.info("Running blackdetect")
		args = [
			'ffmpeg', '-hide_banner',
			'-i', start_path,
			'-vf', 'blackdetect=d=0.1',
			'-f', 'null', '/dev/null'
		]
		proc = subprocess.Popen(args, stderr=subprocess.PIPE)
		out, err = proc.communicate()
		if proc.wait() != 0:
			raise Exception("ffmpeg exited {}\n{}".format(proc.wait(), err))
		lines = [
			line for line in err.strip().split('\n')
			if line.startswith('[blackdetect @ ')
		]
		if len(lines) == 1:
			line, = lines
			black_end = line.split(' ')[4]
			assert black_end.startswith('black_end:')
			time_offset = float(black_end.split(':')[1])
		else:
			found = len(lines)
			logger.warning("Unable to detect start (expected 1 black interval, but found {})".format(found))
			raise CantFindStart(racer, found)
		time_offset = datetime.timedelta(seconds=time_offset)

		# start each racer's finish video at TIME_OFFSET later, so they are the same
		# time since their actual start.
		finish_base = end + time_offset
		finish_start, finish_end = add_range(finish_base, finish_range)
		finish_path = os.path.join(output_dir, "finish-{}.mp4".format(racer_number))
		finish_paths.append(finish_path)
		logger.info("Got time offset of {}, cutting finish at finish_base {}".format(time_offset, finish_base))
		cut_to_file(logger, finish_path, base_dir, racer, finish_start, finish_end)

	temp_path = "{}.tmp.mp4".format(result_path)
	args = ['ffmpeg']
	for path in finish_paths:
		args += ['-i', path]
	args += [
		'-r', '60',
		'-filter_complex', 'hstack',
		'-y', temp_path,
	]

	logger.info("Cutting final result")
	subprocess.check_call(args)
	# atomic rename so that if result_path exists at all, we know it is complete and correct
	os.rename(temp_path, result_path)
	logger.info("Review done")
	return result_path
