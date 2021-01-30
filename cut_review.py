
"""
Tools for reviewing races

Database info:

matches maps to multiple races via match_races (on match_id)
matches links to racers and cawmentator:
	matches.racer_{1,2}_id
	matches.cawmentator_id
races contains start time:
	races.timestamp
races maps to multiple runs via race_runs
race_runs contains time for each racer
	race_runs.time: centiseconds
	race_runs.rank: 1 for fastest time

"""

import datetime
import logging
import os
import subprocess
from getpass import getpass

import argh
import mysql.connector

from common.segments import get_best_segments, full_cut_segments



def ts(dt):
	return dt.strftime("%FT%T")


class NoSegments(Exception):
	pass


def cut_to_file(filename, base_dir, stream, start, end, variant='source', frame_counter=False):
	logging.info("Cutting {}".format(filename))
	segments = get_best_segments(
		os.path.join(base_dir, stream, variant).lower(),
		start, end,
	)
	if None in segments:
		logging.warning("Cutting {} ({} to {}) but it contains holes".format(filename, ts(start), ts(end)))
	if not segments or set(segments) == {None}:
		raise NoSegments("Can't cut {} ({} to {}): No segments".format(filename, ts(start), ts(end)))
	filter_args = ["-vf", "scale=-1:720"]
	if frame_counter:
		filter_args += [
			"-vf", "drawtext="
				"fontfile=DejaVuSansMono.ttf"
				":fontcolor=white"
				":text='%{e\:t}'"
				":x=(w-tw)/2"
				":y=h-(2*lh)",
		]
	encoding_args = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-f', 'mp4']
	with open(filename, 'w') as f:
		for chunk in full_cut_segments(segments, start, end, filter_args + encoding_args):
			f.write(chunk)


def main(match_id, race_number, host='condor.live', user='necrobot-read', password=None, database='condor_x2', base_dir='/srv/wubloader', output_dir='/tmp'):
	logging.basicConfig(level=logging.INFO)

	match_id = int(match_id)
	race_number = int(race_number)

	if password is None:
		password = getpass("Password? ")
	conn = mysql.connector.connect(
		host=host, user=user, password=password, database=database,
	)

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
		WHERE match_info.completed AND race_runs.rank = 1
			AND match_info.match_id = %(match_id)s
			AND match_races.race_number = %(race_number)s
	""", {'match_id': match_id, 'race_number': race_number})


	data = cur.fetchall()
	data = [
		[item.encode('utf-8') if isinstance(item, unicode) else item for item in row]
		for row in data
	]

	if not data:
		raise Exception("No such race")
	assert len(data) == 1, repr(data)

	(racer1, racer2, start, duration), = data
	end = start + datetime.timedelta(seconds=duration/100.)

	finish_paths = []

	for racer in (racer1, racer2):
		start_path = os.path.join(output_dir, "start-{}.mp4".format(racer))
		cut_to_file(start_path, base_dir, racer, start, start + datetime.timedelta(seconds=5), frame_counter=True)
		print "Cut to {}".format(start_path)
		time_offset = float(raw_input("What timestamp of this video do we start at? "))
		time_offset = datetime.timedelta(seconds=time_offset)

		# start each racer's finish video at TIME_OFFSET later, so they are the same
		# time since their actual start.
		finish_start = end - datetime.timedelta(seconds=7) + time_offset
		finish_path = os.path.join(output_dir, "finish-{}.mp4".format(racer))
		finish_paths.append(finish_path)
		cut_to_file(finish_path, base_dir, racer, finish_start, finish_start + datetime.timedelta(seconds=5))

	output_path = os.path.join(output_dir, "result.mp4")
	args = ['ffmpeg']
	for path in finish_paths:
		args += ['-i', path]
	args += [
		'-r', '60',
		'-filter_complex', 'hstack',
		'-y', output_path,
	]

	subprocess.check_call(args)
	print "Review cut to file {}".format(output_path)


if __name__ == '__main__':
	argh.dispatch_command(main)
