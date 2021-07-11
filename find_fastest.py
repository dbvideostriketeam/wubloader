
"""
Output a list of fastest races in a league

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
import re
import subprocess
from getpass import getpass
from uuid import uuid4

import argh
import mysql.connector

def main(league, limit=144,
	host='condor.live', user='necrobot-read', password='necrobot-read', database='condor_x2',
):
	logging.basicConfig(level=logging.INFO)

	if password is None:
		password = getpass("Password? ")
	conn = mysql.connector.connect(
		host=host, user=user, password=password, database=database,
	)

	cur = conn.cursor()
	cur.execute("""
		SELECT
			match_info.match_id as match_id,
			match_races.race_number as race_number
		FROM match_info
		JOIN match_races ON (match_info.match_id = match_races.match_id)
		JOIN races ON (match_races.race_id = races.race_id)
		JOIN race_runs ON (races.race_id = race_runs.race_id)
		WHERE race_runs.rank = 1
			AND match_info.league_tag = %(league)s
		ORDER BY race_runs.time ASC
		LIMIT %(limit)s
	""", {'limit': limit, 'league': league})

	data = cur.fetchall()
	data = [
		[item.encode('utf-8') if isinstance(item, unicode) else item for item in row]
		for row in data
	]

	for i, (match_id, race_number) in enumerate(data):
		print i, match_id, race_number

if __name__ == '__main__':
	argh.dispatch_command(main)
