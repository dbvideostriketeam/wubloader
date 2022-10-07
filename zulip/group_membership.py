
import gevent.monkey
gevent.monkey.patch_all()

import logging

import requests

logging.basicConfig(level='INFO')

class Client(object):
	def __init__(self, base_url, api_key):
		self.base_url = base_url
		self.api_key = api_key
		self.session = requests.Session()

	def request(self, method, *path, **params):
		# TODO api key
		if method == 'GET':
			args = {"params": params}
		else:
			args = {"data": params}
		url = "/".join([self.base_url, "api/v1"] + list(path))
		resp = session.request(method, url, **args)
		resp.raise_for_status()
		return resp.json()

def get_membership(client):
	"""Returns {group id: member set}"""
	return {
		group["id"]: set(group["members"])
		for group in client.request("GET", "user_groups")["user_groups"]
	}

def update_members(client, group_id, old_members, new_members):
	added = new_members - old_members
	removed = old_members - new_members
	client.request("POST", "user_groups", group_id, "members", add=list(added), delete=list(removed))

def determine_members(schedules, hour):
	return set(
		user for user, schedule in schedules.items()
		if hour in schedule
	)

def run_hour(client, user_map, groups, hour):
	logging.info("Setting groups for hour {}".format(hour))
	members = get_membership(client)
	def run_group(group_id, schedules):
		new_members = determine_members(schedules, hour)
		new_members = set(user_map[id] for id in new_members)
		assert group_id in members, "group {} doesn't exist".format(group_id)
		update_members(client, group_id, members[group_id], new_members)
	gevent.pool.Group().map(run_group, groups.items())

def parse_config(conf_file):
	MAX_DAYS=8
	with open(conf_file) as f:
		config = yaml.safe_load(f)
	assert "url" in config
	assert "api_key" in config
	assert "start_time" in config
	all_users = set()
	for group_id, schedules in config["groups"]:
		all_users |= set(schedules.keys())
		for user_id, schedule in schedules:
			hours = set()
			for part in scuedule.split(","):
				part = part.strip()
				if part.endswith("/24"):
					hour = int(part.split('/')[0])
					hours |= set(24 * day + hour for day in range(MAX_DAYS))
				elif part in "ZDAN":
					shift = "ZDAN".index(part)
					hours |= set(hour for hour in range(24 * MAX_DAYS) if (hour % 24) // 6 == shift)
				else:
					hours.add(int(part))
			schedules[user_id] = hours
	missing = all_users - set(config["members"])
	assert not missing, "missing: {}".format(", ".join(missing))
				

def main(conf_file, hour=-1):
	"""
	config:
		url: the base url of the instance
		api_key: authentication
		start_time: Time of the first hour, as epoch int
		members:
			NAME: USER_ID
		groups:
			GROUP_ID:
				NAME: SCHEDULE
	Where:
		schedule: Comma-seperated list of hours
		hour: One of:
			Integer hour, representing that hour of the run
			N/24, expanding to hour N of each day (eg. 0/24 is midnight each day)
			Z | D | A | N, expanding to all hours of Zeta, Dawn Guard, Alpha Flight, Night Watch respectively.
	"""
	config = parse_config(conf_file)
	client = Client(config["url"], config["api_key"])
	user_map = config["members"]
	groups = config["groups"]
	if hour >= 0:
		run_hour(client, user_map, groups, hour)
		return
	while True:
		hour = (time.time() - start_time) // 3600
		run_hour(client, user_map, groups, hour)
		next_hour = start_time + 3600 * (hour + 1)
		remaining = next_hour - time.time()
		if remaining > 0:
			time.sleep(remaining)

if __name__ == '__main__':
	argh.dispatch_command(main)
