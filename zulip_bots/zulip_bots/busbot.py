"""
This bot queries the InfluxDB that stores game events from the Desert Bus game.
For each  event, it:
- checks that the event hasn't already been processed
- formats a message with the event details
- posts it to Zulip.

"""

import json
import logging
import os
import time

import argh

from common.requests import InstrumentedSession
from common import zulip

from .config import common_setup, get_config

requests = InstrumentedSession()

QUERY = """
SELECT time, event, details FROM desertbus_event
{where}
ORDER BY time
"""
HONK_COUNT_QUERY = """
SELECT COUNT(*) AS count FROM desertbus_event
WHERE event = 'honk' AND time <= TIMESTAMP '{timestamp}'
"""
GAME_STATE_QUERY = """
SELECT game_state, driver_name, time_of_day FROM desertbus
ORDER BY time DESC
LIMIT 1
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
def query_events(url, database, token, query):
    endpoint = f"{url.rstrip('/')}/api/v3/query_sql"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

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
        timestamp = last_event_time.replace("'", "''")
        conditions.append(f"time > TIMESTAMP '{timestamp}'")
    if honk_modulo <= 0:
        conditions.append("event != 'honk'")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return QUERY.format(where=where)


def count_honks(url, database, token, last_event_time):
    timestamp = last_event_time.replace("'", "''")
    query = HONK_COUNT_QUERY.format(timestamp=timestamp)
    row = next(query_events(url, database, token, query))
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


def driver_state_message(previous_game_state, game_state, driver_name):
    if previous_game_state == 0 and game_state == 3:
        return f"YOUR DRIVER IS: {driver_name}"


def time_of_day_message(previous_time_of_day, time_of_day):
    if previous_time_of_day is not None and previous_time_of_day != time_of_day:
        return f"Game Time of Day: {time_of_day}"


def validate_config(config):
    required = (
        "influx_url",
        "influx_database",
        "state",
        "zulip_url",
        "zulip_email",
        "zulip_api_key",
    )
    missing = [key for key in required if not config.get(key)]
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
    previous_game_state = None
    previous_time_of_day = None
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
        logging.info(f"Querying InfluxDB for game data events after {last_event_time}")
        for event in query_events(
            config["influx_url"],
            config["influx_database"],
            config.get("influx_token"),
            event_query(last_event_time, honk_modulo),
        ):
            is_honk = event["event"] == "honk"
            if is_honk:
                honk_count += 1
            # only post every Nth honk
            should_post = (
                not is_honk
                or (honk_modulo > 0 and honk_count % honk_modulo == 0)
            )
            message = event_to_message(event, honk_count if is_honk else None)
            last_event_time = event["time"]
            if test:
                if should_post:
                    print(f"{stream}->{topic}: {message}")
            else:
                if should_post:
                    zulip_client.send_to_stream(stream, topic, message)
                save_state(config["state"], last_event_time, honk_count)

        game_state = next(query_events(
            config["influx_url"],
            config["influx_database"],
            config.get("influx_token"),
            GAME_STATE_QUERY,
        ), None)
        if game_state is not None:
            message = driver_state_message(
                previous_game_state,
                game_state["game_state"],
                game_state["driver_name"],
            )
            if message is not None:
                if test:
                    print(f"{stream}->{topic}: {message}")
                else:
                    zulip_client.send_to_stream(stream, topic, message)
            previous_game_state = game_state["game_state"]
            message = time_of_day_message(
                previous_time_of_day,
                game_state["time_of_day"],
            )
            if message is not None:
                if test:
                    print(f"{stream}->{topic}: {message}")
                else:
                    zulip_client.send_to_stream(stream, topic, message)
            previous_time_of_day = game_state["time_of_day"]

        if once:
            break
        remaining = started + interval - time.time()
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    argh.dispatch_command(main)
