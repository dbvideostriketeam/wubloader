"""
Game Events queries the InfluxDB that stores game events from the Desert Bus game.
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
import requests

from common import zulip

from .config import common_setup, get_config

QUERY = """
SELECT time, event, details FROM desertbus_events
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
def query_events(url, database, token, query):
    endpoint = f"{url.rstrip('/')}/api/v3/query_sql"
    headers = {}
    if token:
        headers["Authorization"] = token

    with requests.post(
        endpoint,
        headers=headers,
        json={"db": database, "q": query, "format": "jsonl"},
        stream=True,
        timeout=(10, 60),
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if line:
                yield json.loads(line)


def load_state(path):
    with open(path, encoding="utf-8") as state_file:
        return json.load(state_file)


def save_state(path, last_event_time):
    with open(path, "w", encoding="utf-8") as state_file:
        state_file.write(json.dumps(last_event_time) + "\n")


def event_query(last_event_time):
    if last_event_time is None:
        where = ""
    else:
        timestamp = last_event_time.replace("'", "''")
        where = f"WHERE time > TIMESTAMP '{timestamp}'"
    return QUERY.format(where=where)


def parse_details(details):
    if isinstance(details, str):
        return json.loads(details)


def event_to_message(event):
    event_type = event["event"]
    details = parse_details(event.get("details"))
    lines = [f"**{EVENT_NAMES.get(event_type, event_type.replace('_', ' ').title())}**"]
    lines.append(f"Time: `{event['time']}`")
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
        raise ValueError(f"Missing required GameEventsBot config values: {', '.join(missing)}")


def main(
    config_file,
    interval=1,
    metrics_port=8021,
    stream="bot-spam",
    topic="Game Events",
    test=False,
    once=False,
):
    common_setup(metrics_port)
    config = get_config(config_file)
    validate_config(config)

    if interval <= 0:
        raise ValueError("Polling interval must be greater than zero")

    last_event_time = load_state(config["state"]) if os.path.exists(config["state"]) else None

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
            event_query(last_event_time),
        ):
            message = event_to_message(event)
            last_event_time = event["time"]
            if test:
                print(f"{stream}->{topic}: {message}")
            else:
                zulip_client.send_to_stream(stream, topic, message)
                save_state(config["state"], last_event_time)

        if once:
            break
        remaining = started + interval - time.time()
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    argh.dispatch_command(main)
