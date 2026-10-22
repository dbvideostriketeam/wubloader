"""
GameEventsbot queries the InfluxDB that stores game events from the Desert Bus game.
For each  event, it:
- checks that the event hasn't already been processed
- formats a message with the event details
- posts it to Zulip.

"""

import hashlib
import json
import logging
import os
import time

import argh
import requests

from common import atomic_write
from common import zulip

from .config import common_setup, get_config

QUERY = """
SELECT time, event, details FROM desertbus_events
ORDER BY time
"""
# TODO(?): Query from a persisted timestamp watermark to avoid rescanning all events each interval.
# Probably not a worry given the volume of events in a single run

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



def query_events(url, database, token):
    endpoint = f"{url.rstrip('/')}/api/v3/query_sql"
    headers = {}
    if token:
        headers["Authorization"] = token

    with requests.post(
        endpoint,
        headers=headers,
        json={"db": database, "q": QUERY, "format": "jsonl"},
        stream=True,
        timeout=(10, 60),
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if line:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("InfluxDB query returned a non-object event row")
                yield event


def event_key(event):
    identity = {
        "time": event["time"],
        "event": event["event"],
        "details": parse_details(event.get("details")),
    }
    content = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_state(path):
    if not os.path.exists(path):
        return {"initialized": False, "seen": set()}

    with open(path, encoding="utf-8") as state_file:
        data = json.load(state_file)
    if not isinstance(data, dict) or not isinstance(data.get("seen"), list):
        raise ValueError(f"Invalid GameEventsBot state file {path!r}")
    if not isinstance(data.get("initialized"), bool):
        raise ValueError(f"Invalid GameEventsBot initialization state in {path!r}")
    if not all(isinstance(key, str) for key in data["seen"]):
        raise ValueError(f"Invalid event keys in GameEventsBot state file {path!r}")
    return {"initialized": data["initialized"], "seen": set(data["seen"])}


def save_state(path, state):
    atomic_write(path, json.dumps({
        "initialized": state["initialized"],
        "seen": sorted(state["seen"]),
    }) + "\n")


def parse_details(details):
    if isinstance(details, str):
        details = json.loads(details)
    if not isinstance(details, dict):
        raise ValueError("Game event details must be a JSON object")
    return details


def event_to_message(event):
    if "time" not in event or "event" not in event:
        raise ValueError("Game event row must include time and event columns")

    event_type = event["event"]
    details = parse_details(event.get("details"))
    lines = [f"**{EVENT_NAMES.get(event_type, event_type.replace('_', ' ').title())}**"]
    lines.append(f"Time: `{event['time']}`")
    for key, value in details.items():
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
    if not isinstance(config, dict):
        raise ValueError("GameEventsBot config must be a mapping")
    required = (
        "influx_url",
        "influx_database",
        "state",
        "zulip_url",
        "zulip_email",
        "zulip_api_key",
        "stream",
        "topic",
    )
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"Missing required GameEventsBot config values: {', '.join(missing)}")


def main(
    config_file,
    interval=None,
    metrics_port=8021,
    stream=None,
    topic=None,
    test=False,
    once=False,
    send_existing=False,
):
    common_setup(metrics_port)
    config = get_config(config_file)
    validate_config(config)

    interval = config.get("interval", 60) if interval is None else interval
    if interval <= 0:
        raise ValueError("Polling interval must be greater than zero")

    stream = stream or config["stream"]
    topic = topic or config["topic"]
    send_existing = send_existing or config.get("send_existing", False)
    state = load_state(config["state"])

    zulip_client = None
    if not test:
        zulip_client = zulip.Client(
            config["zulip_url"],
            config["zulip_email"],
            config["zulip_api_key"],
        )

    while True:
        started = time.time()
        logging.info("Querying InfluxDB for game data events")
        state_changed = False
        for event in query_events(
            config["influx_url"],
            config["influx_database"],
            config.get("influx_token"),
        ):
            key = event_key(event)
            if key in state["seen"]:
                continue

            if not state["initialized"] and not send_existing and not test:
                state["seen"].add(key)
                state_changed = True
                continue

            message = event_to_message(event)
            if test:
                print(f"{stream}->{topic}: {message}")
            else:
                zulip_client.send_to_stream(stream, topic, message)
                state["seen"].add(key)
                save_state(config["state"], state)
            state_changed = True

        if not state["initialized"]:
            state["initialized"] = True
            state_changed = True
        if state_changed and not test:
            save_state(config["state"], state)

        if once:
            break
        remaining = started + interval - time.time()
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    argh.dispatch_command(main)
