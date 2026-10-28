"""
This bot queries the InfluxDB that stores game events from the Desert Bus game.
For each  event, it:
- checks that the event hasn't already been processed
- formats a message with the event details
- posts it to Zulip.

"""

import datetime
import json
import logging
import os
import time

import argh

from common.requests import InstrumentedSession
from common.dateutil import parse_utc_only
from common import zulip

from .config import common_setup, get_config

requests = InstrumentedSession()

MAX_TIME_HOURS = 24

HONK_COUNT_QUERY = """
SELECT COUNT(*) AS count FROM desertbus_event
WHERE event = 'honk' AND time <= TIMESTAMP '{timestamp}'
"""
GAME_STATE_QUERY = """
SELECT game_state, driver_name, phase FROM desertbus
WHERE time >= now() - INTERVAL '5 minutes'
ORDER BY time DESC
LIMIT 1
"""
BUS_QUERY = """
SELECT * FROM desertbus
WHERE time > '{start}' AND time <= '{end}'
ORDER BY time
"""
EVENT_QUERY = """
SELECT * FROM desertbus_event
{where}
ORDER BY time
"""


EVENT_NAMES = {
    "bus_stop": "Bus stop",
    "bus_stop_missed": "Missed bus stop",
    "crash": "Crash",
    "point": "Point",
    "bug_splat": "Bug splat",
    "honk": "Honk",
}

DETAIL_NAMES = {
    "leg_miles": "Leg miles",
    "stopped_s": "Stopped for",
    "state": "State",
    "cause": "Cause",
    "lateral_raw": "Lateral position",
    "points": "Points",
    "odometer_miles": "Odometer",
    "leg": "Leg",
    "x": "Position",
    "speed_mph": "Speed",
}


def query_database(url, database, token, query):
    endpoint = f"{url.rstrip('/')}/api/v3/query_sql"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    logging.debug("Making query: %s", " ".join(query.splitlines()).strip())
    with requests.post(
        endpoint,
        headers=headers,
        json={"db": database, "q": query, "format": "jsonl"},
        stream=True,
        timeout=(10, 60),
        metric_name="influx_query",
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if line:
                yield json.loads(line)

def append_json(path, data):
    if path is None:
        return
    with open(path, 'a') as archive_file:
        for datum in data:
            archive_file.write(json.dumps(datum) + '\n')


def latest_entry(path):
    with open(path) as archive_file:
        lines = archive_file.readlines()
    if not lines:
        return None
    return json.loads(lines[-1])['time']


def load_state(path):
    with open(path) as state_file:
        state = json.load(state_file)
    if isinstance(state, dict):
        return state["last_event_time"], state["honk_count"]
    return state, None


def save_state(path, last_event_time, honk_count):
    with open(path, "w") as state_file:
        state_file.write(json.dumps({
            "last_event_time": last_event_time,
            "honk_count": honk_count,
        }) + "\n")


def event_query(last_event_time, honk_modulo):
    conditions = []
    if last_event_time is not None:
        end_time = (parse_utc_only(last_event_time) + datetime.timedelta(hours=MAX_TIME_HOURS)).isoformat()
        timestamp = last_event_time.replace("'", "''")
        end_time = end_time.replace("'", "''")
        conditions.append(f"time > TIMESTAMP '{timestamp}'")
        conditions.append(f"time <= TIMESTAMP '{end_time}'")
    if honk_modulo <= 0:
        conditions.append("event != 'honk'")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return EVENT_QUERY.format(where=where)

def bus_query(last_bus_time):
    end = (parse_utc_only(last_bus_time) + datetime.timedelta(hours=MAX_TIME_HOURS)).isoformat()
    return BUS_QUERY.format(start=last_bus_time, end=end)


def count_honks(url, database, token, last_event_time):
    timestamp = last_event_time.replace("'", "''")
    query = HONK_COUNT_QUERY.format(timestamp=timestamp)
    row = next(query_database(url, database, token, query))
    return row["count"]


def parse_details(details):
    return json.loads(details)


def event_to_message(event, honk_count=None):
    event_type = event["event"]
    details = parse_details(event["details"])
    event_name = EVENT_NAMES.get(event_type, event_type.replace("_", " ").title())
    if event_type == "honk":
        event_name = f"{event_name} #{honk_count}"
    lines = [f"**{event_name}**"]
    lines.append(f"Time: <time:{event['time']}Z>")
    for key, value in details.items():
        if key == "lateral_raw":
            # Normalize to (-1, 1) value
            value = (value - 0x6C00) / 0x4800
        label = DETAIL_NAMES.get(key, key.replace("_", " ").title())
        if key.endswith("_miles"):
            value = f"{value} mi"
        elif key.endswith("_mph"):
            value = f"{value} mph"
        elif key.endswith("_s"):
            value = f"{value} s"
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


def driver_state_message(
    previous_game_state,
    game_state,
    previous_driver_name,
    driver_name,
):
    # Getting a point is the same state change as new game (0 to 3), so don't re-announce the same driver
    if (
        previous_game_state == 0
        and game_state == 3
        and previous_driver_name is not None
        and previous_driver_name != driver_name
    ):
        return f"YOUR DRIVER IS: {driver_name}"


def time_of_day_message(previous_phase, phase):
    if previous_phase is not None and previous_phase != phase:
        return f"Game Time of Day: {phase}"


def validate_config(config):
    required = (
        "influx_url",
        "influx_database",
        "state",
        "zulip_url",
        "zulip_email",
        "zulip_api_key",
    )
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing required BusBot config values: {', '.join(missing)}")


def main(
    config_file,
    interval=1,
    metrics_port=8021,
    stream="bot-spam",
    topic="Bus Bot",
    test=False,
    once=False,
    archive_start=None
):
    common_setup(metrics_port)
    config = get_config(config_file)
    validate_config(config)

    if interval <= 0:
        raise ValueError("Polling interval must be greater than zero")

    if os.path.exists(config["state"]):
        last_event_time, honk_count = load_state(config["state"])
    else:
        last_event_time, honk_count = None, None

    bus_archive_file = config.get("bus_archive")
    last_bus_time = None
    if bus_archive_file and os.path.exists(bus_archive_file):
        last_bus_time = latest_entry(bus_archive_file)
    if last_bus_time is None:
        last_bus_time = archive_start
    if last_bus_time is None:
        last_bus_time = datetime.datetime.utcnow().isoformat()

    events_archive_file = config.get("events_archive")
    if events_archive_file and os.path.exists(events_archive_file):
        last_archive_event_time = latest_entry(events_archive_file)
    else:
        last_archive_event_time = None

    previous_game_state = None
    previous_driver_name = None
    previous_phase = None
    honk_modulo = config["honk_modulo"]
    if honk_modulo > 0 and honk_count is None:
        honk_count = (
            count_honks(
                config["influx_url"],
                config["influx_database"],
                config.get("influx_token"),
                last_event_time,
            )
            if last_event_time is not None
            else 0
        )
    elif honk_modulo <= 0:
        honk_count = None

    zulip_client = None
    if not test:
        zulip_client = zulip.Client(
            config["zulip_url"],
            config["zulip_email"],
            config["zulip_api_key"],
        )

    while True:
        started = time.time()
        logging.debug("Querying InfluxDB for game data after %s", last_bus_time)
        results = list(query_database(
            config["influx_url"],
            config["influx_database"],
            config.get("influx_token"),
            bus_query(last_bus_time)
        ))
        append_json(bus_archive_file, results)
        if results:
            last_bus_time = results[-1]['time']


        logging.debug("Querying InfluxDB for game events after %s", last_event_time)
        events = list(query_database(
            config["influx_url"],
            config["influx_database"],
            config.get("influx_token"),
            event_query(last_archive_event_time, honk_modulo),
        ))
        append_json(events_archive_file, events)
        if events:
            last_archive_event_time = events[-1]["time"]
        # remove any archive-only events based on time range
        events = [event for event in events if event["time"] > last_event_time]
        for event in events:
            is_honk = event["event"] == "honk"
            if is_honk:
                honk_count += 1
            # only post every Nth honk
            should_post = event["time"] > last_event_time and (
                not is_honk
                or (honk_modulo > 0 and honk_count % honk_modulo == 0)
            )
            last_event_time = event["time"]
            message = event_to_message(event, honk_count if is_honk else None)
            if test:
                if should_post:
                    print(f"{stream}->{topic}: {message}")
            else:
                if should_post:
                    zulip_client.send_to_stream(stream, topic, message)
                save_state(config["state"], last_event_time, honk_count)

        game_state = next(query_database(
            config["influx_url"],
            config["influx_database"],
            config.get("influx_token"),
            GAME_STATE_QUERY,
        ), None)
        if game_state is not None:
            message = driver_state_message(
                previous_game_state,
                game_state["game_state"],
                previous_driver_name,
                game_state["driver_name"],
            )
            if message is not None:
                if test:
                    print(f"{stream}->{topic}: {message}")
                else:
                    zulip_client.send_to_stream(stream, topic, message)
            previous_game_state = game_state["game_state"]
            previous_driver_name = game_state["driver_name"]
            message = time_of_day_message(
                previous_phase,
                game_state["phase"],
            )
            # Phase reports as "day" immediately after a point (even if it is actually night),
            # so skip this unless we are driving (state 3)
            if message is not None and game_state["game_state"] == 3:
                if test:
                    print(f"{stream}->{topic}: {message}")
                else:
                    zulip_client.send_to_stream(stream, topic, message)
            previous_phase = game_state["phase"]

        if once:
            break

        remaining = started + interval - time.time()
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    argh.dispatch_command(main)
