
import gevent.monkey
gevent.monkey.patch_all()

import csv
import logging
import time
from datetime import datetime, timedelta

import gevent.pool
import argh

from zulip import Client
from config import get_config

logging.basicConfig(level='INFO')


def get_membership(client):
	"""Returns {group id: member set}"""
	return {
		group["id"]: set(group["members"])
		for group in client.request("GET", "user_groups")["user_groups"]
	}

def update_members(client, group_id, old_members, new_members):
	logging.info(f"Updating group {group_id}: {old_members} -> {new_members}")
	added = new_members - old_members
	removed = old_members - new_members
	if added or removed:
		client.request("POST", "user_groups", group_id, "members", add=list(added), delete=list(removed))

def get_role_at_hour(hours, hour):
	if 0 <= hour < len(hours):
		return hours[hour]
	return ""

def determine_members(schedule, role, hour):
	return set(
		user_id for user_id, (_, hours) in schedule.items()
		if get_role_at_hour(hours, hour) == role
	)

def get_display_name(client, user_id):
	return client.request("GET", "users", user_id)["user"]["full_name"]


def update_groups(client, group_ids, schedule, hour, last):
	logging.info("Setting groups for hour {}".format(hour))
	members = get_membership(client)
	def run_group(item):
		group_name, group_id = item
		new_members = set() if hour == last else determine_members(schedule, group_name, hour)
		assert group_id in members, "group {} doesn't exist".format(group_id)
		update_members(client, group_id, members[group_id], new_members)
	gevent.pool.Group().map(run_group, group_ids.items())


def post_schedule(client, send_client, start_time, schedule, stream, hour, no_mentions, last, omega):
	going_offline = []
	coming_online = []
	display_names = {}
	supervisor = None
	found_any = False
	for user_id, (_, hours) in schedule.items():
		prev = get_role_at_hour(hours, hour - 1)
		now = get_role_at_hour(hours, hour)
		if hour == last:
			now = ""
		if now != "" or prev != "":
			found_any = True
		if now == "Supervisor":
			supervisor = user_id
			if user_id not in display_names:
				display_names[user_id] = gevent.spawn(get_display_name, client, user_id)
		if prev != now:
			if prev != "":
				going_offline.append((prev, user_id))
			if now != "":
				coming_online.append((now, user_id))
			if user_id not in display_names:
				display_names[user_id] = gevent.spawn(get_display_name, client, user_id)

	if not found_any:
		logging.info("Not posting schedule for hour {} as no-one is or was scheduled".format(hour))
		return

	# sort by role
	going_offline.sort()
	coming_online.sort()
	logging.info(f"Going offline: {going_offline}")
	logging.info(f"Coming online: {coming_online}")

	start_time = datetime.utcfromtimestamp(start_time)
	current_time = (start_time + timedelta(hours=hour)).replace(minute=0, second=0, microsecond=0)
	current_time_pst = current_time - timedelta(hours=8)
	hour_pst = current_time_pst.hour
	shift = hour_pst // 6
	shift = ["zeta", "dawn-guard", "alpha-flight", "night-watch"][shift]
	shift_hour = hour_pst % 6 + 1

	if omega >= 0 and hour >= omega:
		shift = "omega"
		shift_hour = hour - omega + 1

	def render_name(user_id, mention=True):
		if no_mentions:
			mention = False
		fallback, _ = schedule[user_id]
		try:
			result = display_names[user_id].get()
		except Exception:
			logging.warning(f"Failed to fetch user {user_id}", exc_info=True)
			return f"**{fallback}**"
		if mention:
			return f"@**{result}|{user_id}**"
		else:
			return f"**{result}**"

	lines = [
		f"**Shift changes for :{shift}: Hour {shift_hour} | Bustime {hour:02d}:00 - {hour+1:02d}:00 | <time:{current_time.isoformat(timespec='minutes')}>:**",
		"Make sure to *mute/unmute* #**current-shift** as needed!",
	]
	if supervisor is None:
		logging.warning("No supervisor found")
	else:
		name = render_name(supervisor, mention=False)
		lines.append(f"Your shift supervisor is {name}")
	if coming_online:
		lines += [
			"",
			"---",
			"Coming online:"
		] + [
			f"- {render_name(user_id)} - {role}"
			for role, user_id in coming_online
		]
	if going_offline:
		lines += [
			"",
			"---",
			"Going offline:"
		] + [
			f"- {render_name(user_id)} - {role}"
			for role, user_id in going_offline
		]
	lines += [
		"",
		"---",
	]
	if hour == last:
		lines += [
			"**Well done everyone, and thank you for all your hard work :heart:**"
		]

	if stream == "DEBUG":
		print("\n".join(lines))
		return

	send_client.send_to_stream(stream, "Schedule", "\n".join(lines))


def parse_schedule(user_ids, schedule_file):
	schedule = {}
	with open(schedule_file) as f:
		for row in csv.reader(f):
			name = row[0]
			if name in ["", "Chat Member", "Hour of the Run"] or name.startswith("-") or name.startswith("["):
				continue
			if name not in user_ids:
				logging.warning(f"No user id known for user {name}")
				continue
			user_id = user_ids[name]
			if user_id in schedule:
				logging.warning(f"Multiple rows for user {name}, merging")
				_, old_hours = schedule[user_id]
				merged = [
					old or new
					for old, new in zip(old_hours, row[1:])
				]
				schedule[user_id] = name, merged
			else:
				schedule[user_id] = name, row[1:]
	return schedule


def main(conf_file, hour=-1, no_groups=False, stream="General", no_mentions=False, no_initial=False, omega=-1, last=-1):
	"""
	config:
		url: the base url of the instance
		api_user: auth used for general api calls
		send_user:
			auth used for sending messages
			defaults to api_user, but you may want a vanity name / avatar
		start_time: Time of the first hour, as UTC timestamp string
		schedule: Path to the schedule CSV file
		members:
			NAME: USER_ID
		groups:
			NAME: GROUP_ID
	authentication is an object {email, api_key}
	"""
	config = get_config(conf_file)
	client = Client(config["url"], config["api_user"]["email"], config["api_user"]["api_key"])
	send_auth = config.get("send_user", config["api_user"])
	send_client = Client(config["url"], send_auth["email"], send_auth["api_key"])
	group_ids = config["groups"]
	start_time = time.strptime(config["start_time"], "%Y-%m-%dT%H:%M:%S")
	schedule = parse_schedule(config["members"], config["schedule"])
	if hour >= 0:
		if not no_groups:
			update_groups(client, group_ids, schedule, hour, last)
		if stream:
			post_schedule(client, send_client, start_time, schedule, stream, hour, no_mentions, last, omega)
		return
	while True:
		hour = int((time.time() - start_time) / 3600)
		if not no_initial:
			if not no_groups:
				update_groups(client, group_ids, schedule, hour, last)
			if stream:
				post_schedule(client, send_client, start_time, schedule, stream, hour, no_mentions, last, omega)
		no_initial = False
		next_hour = start_time + 3600 * (hour + 1)
		remaining = next_hour - time.time()
		if remaining > 0:
			time.sleep(remaining)

if __name__ == '__main__':
	argh.dispatch_command(main)
