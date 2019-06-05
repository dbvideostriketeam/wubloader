
"""
Attempts to cut every race for a league from local segments.

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
import sys
from getpass import getpass

import argh
import mysql.connector

from common.segments import get_best_segments, cut_segments

INFO_QUERY = """
	SELECT
		match_info.racer_1_name as racer_1,
		match_info.racer_2_name as racer_2,
		match_info.cawmentator_name as cawmentator,
		match_info.match_id as match_id,
		match_races.race_number as race_number,
		races.timestamp as start,
		race_runs.time as duration
	FROM match_info
	JOIN match_races ON (match_info.match_id = match_races.match_id)
	JOIN races ON (match_races.race_id = races.race_id)
	JOIN race_runs ON (races.race_id = race_runs.race_id)
	WHERE match_info.completed AND race_runs.rank = 1
"""


def ts(dt):
	return dt.strftime("%FT%T")


class NoSegments(Exception):
	pass


def cut_to_file(filename, base_dir, stream, start, end, variant='source'):
	if os.path.exists(filename):
		return
	logging.info("Cutting {}".format(filename))
	segments = get_best_segments(
		os.path.join(base_dir, stream, variant).lower(),
		start, end,
	)
	if None in segments:
		logging.warning("Cutting {} ({} to {}) but it contains holes".format(filename, ts(start), ts(end)))
	if not segments or set(segments) == {None}:
		raise NoSegments("Can't cut {} ({} to {}): No segments".format(filename, ts(start), ts(end)))
	with open(filename, 'w') as f:
		for chunk in cut_segments(segments, start, end):
			f.write(chunk)


def main(host='condor.host', user='necrobot-read', password=None, database='season_8', base_dir='.', output_dir='.', find=None):
	logging.basicConfig(level=logging.INFO)

	if password is None:
		password = getpass("Password? ")
	conn = mysql.connector.connect(
		host=host, user=user, password=password, database=database,
	)

	if find:
		find = tuple(find.split('-'))

	cur = conn.cursor()
	cur.execute(INFO_QUERY)

	data = cur.fetchall()
	data = [
		[item.encode('utf-8') if isinstance(item, unicode) else item for item in row]
		for row in data
	]

	logging.info("Got info on {} races".format(len(data)))

	for racer1, racer2, cawmentator, match_id, race_number, start, duration in data:
		if find and (racer1.lower(), racer2.lower()) != find:
			continue

		end = start + datetime.timedelta(seconds=duration/100.)
		base_name = "-".join(map(str, [racer1, racer2, match_id, race_number]))

		items = [(racer1, racer1), (racer2, racer2)]
		if cawmentator:
			items.append(("cawmentary", cawmentator))
		for name, stream in items:
			try:
				cut_to_file(
					os.path.join(output_dir, "{}-{}.ts".format(base_name, name)),
					base_dir, stream, start, end,
				)
			except NoSegments as e:
				logging.warning(e)
			except Exception as e:
				logging.exception("Failed to cut {}-{}.ts ({} to {})".format(
					base_name, name, ts(start), ts(end),
				), exc_info=True)


if __name__ == '__main__':
	argh.dispatch_command(main)
