
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

INFO_QUERY = """
	SELECT
		match_info.racer_1_name as racer_1,
		match_info.racer_2_name as racer_2,
		match_info.match_id as match_id,
		match_info.completed as completed
	FROM match_info
"""


def ts(dt):
	return dt.strftime("%FT%T")


def main(find1, find2, host='condor.live', user='necrobot-read', password=None, database='condor_x2'):
	logging.basicConfig(level=logging.INFO)

	if password is None:
		password = getpass("Password? ")
	conn = mysql.connector.connect(
		host=host, user=user, password=password, database=database,
	)

	cur = conn.cursor()
	cur.execute(INFO_QUERY)

	data = cur.fetchall()
	data = [
		[item.encode('utf-8') if isinstance(item, unicode) else item for item in row]
		for row in data
	]

	logging.info("Got info on {} races".format(len(data)))

	find = [(find1.lower(), find2.lower())]
	find.append(find[0][::-1])


	for racer1, racer2, match_id, completed in data:
		if not racer1: racer1 = ''
		if not racer2: racer2 = ''
		if (racer1.lower(), racer2.lower()) in find:
			print "{}: {} vs {}, complete = {}".format(match_id, racer1, racer2, completed)


if __name__ == '__main__':
	argh.dispatch_command(main)
