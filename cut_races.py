
import logging
import os
import tempfile
import shutil
from uuid import uuid4

import argh
import mysql.connector

import cut_sync_race

INFO_QUERY = """
	SELECT
		match_info.racer_1_name as racer_1,
		match_info.racer_2_name as racer_2,
		match_info.cawmentator_name as cawmentator,
		match_info.league_tag as league,
		match_info.match_id as match_id,
		match_races.race_number as race_number,
		races.timestamp as start,
		race_runs.time as duration
	FROM match_info
	JOIN match_races ON (match_info.match_id = match_races.match_id)
	JOIN races ON (match_races.race_id = races.race_id)
	JOIN race_runs ON (races.race_id = race_runs.race_id)
	WHERE match_info.completed AND race_runs.rank = 1
	ORDER BY start ASC
"""

def main(
	output_dir,
	host='condor.live', user='necrobot-read', password='necrobot-read', database='condor_x2',
	base_dir='/srv/wubloader', start_range='0,10', non_interactive=False,
):
	logging.basicConfig(level=logging.INFO)
	start_range = map(int, start_range.split(","))

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

	for racer1, racer2, cawmentator, league, match_id, race_number, start, duration in data:
		base_name = "-".join(map(str, [league, match_id, race_number, racer1, racer2]))

		items = [(racer1, racer1), (racer2, racer2)]
		if cawmentator:
			items.append(("caw-{}".format(cawmentator), cawmentator))
		for name, stream in items:
			output_path = os.path.join(output_dir, "{}-{}.mp4".format(base_name, name))
			if os.path.exists(output_path):
				continue
			logging.info("Cutting {}, starting at {}".format(output_path, start))
			output_temp = "{}.tmp{}.mp4".format(output_path, uuid4())
			temp_dir = tempfile.mkdtemp()
			caw_kwargs = {
				# bypass start checks, cut a longer range instead
				"output_range": (-5, 30),
				"time_offset": 0,
			} if name.startswith("caw-") else {}
			try:
				cut_sync_race.cut_race(
					base_dir, output_temp, temp_dir, stream, start, duration,
					start_range=start_range, non_interactive=non_interactive,
					**caw_kwargs
				)
			except cut_sync_race.NoSegments as e:
				logging.warning(e)
			except Exception as e:
				logging.exception("Failed to cut {}".format(output_path), exc_info=True)
				if not non_interactive:
					raw_input("Press enter to continue ")
			else:
				os.rename(output_temp, output_path)
			finally:
				shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
	argh.dispatch_command(main)
