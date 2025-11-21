
import gevent.monkey
gevent.monkey.patch_all()

import json
import logging
import time
from calendar import timegm
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gevent.pool
import argh

from common.zulip import Client

from .config import common_setup, get_config
from common.sheets import Sheets

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

def get_roles_at_hour(hours, hour):
	if 0 <= hour < len(hours):
		return hours[hour]
	return set()

def determine_members(schedule, role, hour):
	return set(
		user_id for user_id, (_, hours) in schedule.items()
		if role in get_roles_at_hour(hours, hour)
	)

def get_display_name(client, user_id):
	return client.request("GET", "users", user_id)["user"]["full_name"]


def update_groups(client, group_ids, groups_by_shift, schedule, hour, start_time, last):
	if hour < 0:
		logging.info(f"Skipping setting groups due to negative hour of {hour}")
		return

	logging.info("Setting groups for hour {}".format(hour))
	members = get_membership(client)
	_, shift, _, _ = hour_to_shift(hour, start_time)

	def run_group(item):
		group_name, group_id = item
		new_members = set() if hour == last else determine_members(schedule, group_name, hour)
		assert group_id in members, "group {} doesn't exist".format(group_id)
		update_members(client, group_id, members[group_id], new_members)

	def run_group_by_shift(item):
		group_id, shifts = item
		user_ids = set(shifts[shift])
		update_members(client, group_id, members[group_id], user_ids)

	gevent.pool.Group().map(run_group, group_ids.items())
	gevent.pool.Group().map(run_group_by_shift, groups_by_shift.items())


def hour_to_shift(hour, start_time):
	"""Converts an hour number into a datetime, shift number (0-3), shift name, and hour-of-shift (1-6)"""
	start_time = datetime.utcfromtimestamp(start_time)
	current_time = (start_time + timedelta(hours=hour)).replace(minute=0, second=0, microsecond=0)
	current_time_pst = current_time - timedelta(hours=8)
	hour_pst = current_time_pst.hour
	shift = hour_pst // 6
	shift_name = ["zeta", "dawn-guard", "alpha-flight", "night-watch"][shift]
	shift_hour = hour_pst % 6 + 1
	return current_time, shift, shift_name, shift_hour


def post_schedule(client, send_client, start_time, schedule, stream, hour, no_mentions, last, omega):
	going_offline = []
	coming_online = []
	online_by_role = {}
	display_names = {}
	supervisors = []
	found_any = False
	for user_id, (_, hours) in schedule.items():
		prev = get_roles_at_hour(hours, hour - 1)
		now = get_roles_at_hour(hours, hour)
		if hour == last:
			now = set()
		if now or prev:
			found_any = True
		if "Supervisor" in now:
			supervisors.append(user_id)
			if user_id not in display_names:
				display_names[user_id] = gevent.spawn(get_display_name, client, user_id)
		for role in now:
			if role.lower() in ("chatops", "editor", "sheeter"):
				online_by_role.setdefault(role, []).append(user_id)
				if user_id not in display_names:
					display_names[user_id] = gevent.spawn(get_display_name, client, user_id)
		if prev != now:
			for role in prev - now:
				going_offline.append((role, user_id))
			for role in now - prev:
				coming_online.append((role, user_id))
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

	current_time, _, shift, shift_hour = hour_to_shift(hour, start_time)

	if omega >= 0 and hour >= omega:
		shift = "omega"
		shift_hour = hour - omega + 1

	if hour == last:
		shift = "💥"
		shift_hour = "∞"

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

	time_str = f":{shift}: Hour {shift_hour}"
	if hour == 168:
		time_str = "*WEEK TWO*"

	lines = [
		f"**Shift changes for {time_str} | Bustime {hour:02d}:00 - {hour+1:02d}:00 | <time:{current_time.isoformat(timespec='minutes')}>:**",
		"Make sure to *mute/unmute* #**current-shift** as needed!",
	]
	if not supervisors:
		logging.warning("No supervisor found")
	else:
		names = ", ".join([render_name(name, mention=False) for name in supervisors])
		lines.append(f"Your shift supervisors are: {names}")
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
	if online_by_role:
		lines += [
			"",
			"---",
		]
	for role, user_ids in sorted(online_by_role.items()):
		user_ids.sort()
		lines.append("Current {}: {}".format(
			role + ("" if role.endswith("s") else "s"), # bad attempt at pluralization
			", ".join(render_name(user_id, False) for user_id in user_ids),
		))
	lines += [
		"",
		"---",
	]
	if hour == last:
		lines += [
			"# Thank you everyone for making this crazy thing possible, year after year"
			"# 💥",
			"# In memory of ScheduleBot 1970 - 2038",
		]

	if stream == "DEBUG":
		print("\n".join(lines))
		return

	send_client.send_to_stream(stream, "Schedule", "\n".join(lines))


def parse_schedule(sheets_client, user_ids, schedule_sheet_id, schedule_sheet_name):
	schedule = {}
	user_ids = {user.lower(): id for user, id in user_ids.items()}

	try:
		raw_schedule = sheets_client.get_rows(schedule_sheet_id, schedule_sheet_name)
	except Exception:
		return None

	for row in raw_schedule:
		name = row[0].lower()
		if name in ["", "vst member", "hour of the run"] or name.startswith("-") or name.startswith("["):
			continue
		if name not in user_ids:
			logging.warning(f"No user id known for user {name}")
			continue
		user_id = user_ids[name]
		hours = [{hour} if hour != "" else set() for hour in row[1:]]
		if user_id in schedule:
			logging.info(f"Multiple rows for user {name}, merging")
			_, old_hours = schedule[user_id]
			merged = [
				old | new
				for old, new in zip(old_hours, hours)
			]
			schedule[user_id] = name, merged
		else:
			schedule[user_id] = name, hours
	return schedule


def main(conf_file, hour=-1, no_groups=False, stream="General", no_mentions=False, no_initial=False, omega=-1, last=-1, metrics_port=8012):
	"""
	config:
		url: the base url of the instance
		api_user: auth used for general api calls
		send_user:
			auth used for sending messages
			defaults to api_user, but you may want a vanity name / avatar
		start_time: Time of the first hour, as UTC timestamp string
		schedule_sheet_id: Google Sheet ID
		schedule_sheet_name: Google Sheet tab name
		google_credentials_file: (With Read access to schedule_sheet_id)
			Path to json file containing at least:
				client_id
				client_secret
				refresh_token
		members:
			NAME: USER_ID
		groups:
			NAME: GROUP_ID
		groups_by_shift:
			GROUP_ID: [[USER_ID], [USER_ID], [USER_ID], [USER_ID]]
			Populates membership of given group as a hard-coded list of users per DB shift.
			This is NOT reported in start/end of shifts.
	authentication is an object {email, api_key}
	"""
	common_setup(metrics_port)

	config = get_config(conf_file)
	client = Client(config["url"], config["api_user"]["email"], config["api_user"]["api_key"])
	send_auth = config.get("send_user", config["api_user"])
	send_client = Client(config["url"], send_auth["email"], send_auth["api_key"])
	group_ids = config["groups"]
	with open(config["google_credentials_file"]) as f:
		sheets_creds = json.load(f)
	sheets_client = Sheets(
		sheets_creds["client_id"],
		sheets_creds["client_secret"],
		sheets_creds["refresh_token"],
	)
	reload_schedule = lambda: parse_schedule(
		sheets_client,
		config["members"],
		config["schedule_sheet_id"],
		config["schedule_sheet_name"]
	)
	groups_by_shift = {int(id): shifts for id, shifts in config["groups_by_shift"].items()}

	# Accept start time timestamp with or without trailing "Z" indicating UTC.
	start_time = config["start_time"]
	if start_time.endswith("Z"):
		start_time = start_time[:-1]
	start_time = timegm(time.strptime(start_time, "%Y-%m-%dT%H:%M:%S"))

	if hour >= 0:
		# Attempt to download the schedule
		schedule = reload_schedule()
		if schedule is None:
			raise Exception("Schedule failed to download")

		if not no_groups:
			update_groups(client, group_ids, groups_by_shift, schedule, hour, start_time, last)
		if stream:
			post_schedule(client, send_client, start_time, schedule, stream, hour, no_mentions, last, omega)
		return

	schedule = None
	while True:
		hour = int((time.time() - start_time) // 3600)
		# Download a new schedule or use the old one if there's a failure
		new_schedule = reload_schedule()
		if new_schedule is not None:
			schedule = new_schedule
		if schedule is None:
			raise Exception("Schedule failed to download")

		if not no_initial:
			if not no_groups:
				update_groups(client, group_ids, groups_by_shift, schedule, hour, start_time, last)
			if stream:
				post_schedule(client, send_client, start_time, schedule, stream, hour, no_mentions, last, omega)
		no_initial = False
		next_hour = start_time + 3600 * (hour + 1)
		remaining = next_hour - time.time()
		if remaining > 0:
			time.sleep(remaining)

if __name__ == '__main__':
	argh.dispatch_command(main)
