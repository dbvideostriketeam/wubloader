
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

from getpass import getpass

import argh
import mysql.connector


INFO_QUERY = """
	SELECT
		match_info.racer_1_name as racer_1,
		match_info.racer_2_name as racer_2,
		match_info.cawmentator_name as cawmentator,
		match_info.match_id as match_id
		match_races.race_number as race_number,
		races.timestamp as start,
		race_runs.time as duration
	FROM match_info
	JOIN match_races ON (match_info.match_id = match_races.match_id)
	JOIN races ON (match_races.race_id = races.race_id)
	JOIN race_runs ON (races.race_id = race_runs.race_id)
	WHERE match_info.completed AND race_runs.rank = 1
"""


def cut_to_file()


def main(host='condor.host', user='necrobot-read', password=None, database='season_8'):
	if password is None:
		password = getpass("Password? ")
	conn = mysql.connector.connect(
		host=host, user=user, password=password, database=database,
	)

	cur = conn.cursor()
	cur.execute(INFO_QUERY)

	data = cur.fetchall()

	for racer1, racer2, cawmentator, match_id, race_number, start, duration in data:
		end = start + datetime.timedelta(seconds=duration/100.)
		name = "-".join([racer1, racer2, match_id, race_number])



if __name__ == '__main__':
	argh.dispatch_command(main)
