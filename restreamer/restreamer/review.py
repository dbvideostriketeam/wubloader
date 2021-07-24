
import datetime
import json
import logging
import os
import re
import subprocess
from hashlib import sha256
from urlparse import urlparse
from uuid import uuid4
from base64 import b64encode

import mysql.connector

from common.segments import get_best_segments, full_cut_segments



class NoSegments(Exception):
	pass


class RaceNotFound(Exception):
	pass


class CantFindStart(Exception):
	def __init__(self, racer, racer_number, path):
		self.racer = racer
		self.racer_number = racer_number
		self.path = path
	def __str__(self):
		return "Failed to find start point for racer {} ({})".format(self.racer_number, self.racer)


def ts(dt):
	return dt.strftime("%FT%T")


def cut_to_file(logger, filename, base_dir, stream, start, end, variant='source', frame_counter=False):
	"""Returns boolean of whether cut video contained holes"""
	logger.info("Cutting {}".format(filename))
	segments = get_best_segments(
		os.path.join(base_dir, stream, variant).lower(),
		start, end,
	)
	contains_holes = None in segments
	if contains_holes:
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
	return contains_holes


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


def review(
	match_id, race_number, base_dir, db_url, start_range=(0, 10), finish_range=(-5, 10),
	racer1_start=None, racer2_start=None,
):
	"""Cuts a review, returning the following structure:
	{
		racers: [
			{
				name: racer name
				start_path: path to start video, omitted if start given
				start_holes: bool, whether the start video contained holes, omitted if start given
				starts: [start times within video], omitted if start given
				offset: final time offset used
				finish_holes: bool, whether the finish video contained holes
			} for each racer
		]
		result_path: path to result video
	}
	"""
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
		raise RaceNotFound("Could not find race number {} of match {}".format(race_number, match_id))
	assert len(data) == 1, repr(data)

	(racer1, racer2, start, duration), = data
	end = start + datetime.timedelta(seconds=duration/100.)

	# cache hash encapsulates all input args
	cache_hash = sha256(str((match_id, race_number, start_range, finish_range, racer1_start, racer2_start)))
	cache_str = b64encode(cache_hash.digest(), "-_")[:12]

	output_name = "{}-{}-{}-{}".format(match_id, racer1, racer2, race_number)
	output_dir = os.path.join(base_dir, "reviews", output_name)
	if not os.path.exists(output_dir):
		os.makedirs(output_dir)
	result_name = "review_{}.mp4".format(cache_str)
	result_path = os.path.join(output_dir, result_name)
	cache_path = os.path.join(output_dir, "cache_{}.json".format(cache_str))
	if os.path.exists(result_path) and os.path.exists(cache_path):
		logger.info("Result already exists for {}, reusing".format(result_path))
		with open(cache_path) as f:
			return json.load(f)

	finish_paths = []
	result_info = {
		"result_path": result_path
	}

	for racer_index, (racer, time_offset) in enumerate(((racer1, racer1_start), (racer2, racer2_start))):
		nonce = str(uuid4())
		racer_number = racer_index + 1
		racer_info = {"name": racer}
		result_info.setdefault("racers", []).append(racer_info)

		if time_offset is None:
			start_path = os.path.join(output_dir, "start-{}-{}-{}.mp4".format(racer_number, cache_str, nonce))
			racer_info["start_path"] = start_path
			logger.info("Cutting start for racer {} ({})".format(racer_number, racer))
			start_start, start_end = add_range(start, start_range)
			racer_info["start_holes"] = cut_to_file(logger, start_path, base_dir, racer, start_start, start_end)

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
				line for line in re.split('[\r\n]', err.strip())
				if line.startswith('[blackdetect @ ')
			]
			starts = []
			racer_info["starts"] = starts
			for line in lines:
				black_end = line.split(' ')[4]
				assert black_end.startswith('black_end:')
				starts.append(float(black_end.split(':')[1]))

			# unconditionally re-cut a start, this time with frame counter.
			# TODO avoid the repeated work and do cut + blackdetect + frame counter all in one pass
			cut_to_file(logger, start_path, base_dir, racer, start_start, start_end, frame_counter=True)

			if not starts:
				raise CantFindStart(racer, racer_number, start_path)

			if len(starts) > 1:
				logging.warning("Found multiple starts, picking first: {}".format(starts))
			time_offset = starts[0]

		racer_info["offset"] = time_offset
		time_offset = datetime.timedelta(seconds=start_range[0] + time_offset)

		# start each racer's finish video at TIME_OFFSET later, so they are the same
		# time since their actual start.
		finish_base = end + time_offset
		finish_start, finish_end = add_range(finish_base, finish_range)
		finish_path = os.path.join(output_dir, "finish-{}-{}.mp4".format(racer_number, nonce))
		finish_paths.append(finish_path)
		logger.info("Got time offset of {}, cutting finish at finish_base {}".format(time_offset, finish_base))
		racer_info["finish_holes"] = cut_to_file(logger, finish_path, base_dir, racer, finish_start, finish_end)

	temp_path = "{}.{}.mp4".format(result_path, str(uuid4()))
	args = ['ffmpeg']
	for path in finish_paths:
		args += ['-i', path]
	args += [
		'-r', '60',
		'-filter_complex', 'hstack',
		'-y', temp_path,
	]

	cache_temp = "{}.{}.json".format(cache_path, str(uuid4()))
	with open(cache_temp, 'w') as f:
		f.write(json.dumps(result_info))
	os.rename(cache_temp, cache_path)

	logger.info("Cutting final result")
	subprocess.check_call(args)
	# atomic rename so that if result_path exists at all, we know it is complete and correct
	os.rename(temp_path, result_path)
	logger.info("Review done: {}".format(result_info))
	return result_info
