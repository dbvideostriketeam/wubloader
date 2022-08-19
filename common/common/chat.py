
import json
import logging
import os
from datetime import datetime, timedelta

from common import listdir
from common.stats import timed
from common.segments import hour_paths_for_range


# How long each batch is
BATCH_INTERVAL = 60


def format_batch(messages):
	# We need to take some care to have a consistent ordering and format here.
	# We use a "canonicalised JSON" format, which is really just whatever the python encoder does,
	# with compact separators and sorted keys.
	messages = [
		(message, json.dumps(message, separators=(',', ':'), sort_keys=True))
		for message in messages
	]
	# We sort by timestamp, then timestamp range, then if all else fails, lexiographically
	# on the encoded representation.
	messages.sort(key=lambda item: (item[0]['time'], item[0]['time_range'], item[1]))
	return "\n".join(line for message, line in messages)


def get_batch_files(path, batch_time):
	"""Returns list of batch filepaths for a given batch time as unix timestamp"""
	hour = datetime.utcfromtimestamp(batch_time).strftime("%Y-%m-%dT%H")
	time = datetime.utcfromtimestamp(batch_time).strftime("%M:%S")
	hourdir = os.path.join(path, hour)
	return [
		os.path.join(hourdir, name)
		for name in listdir(hourdir)
		if name.startswith(time) and name.endswith(".json")
	]


def get_batch_file_range(hours_path, start, end):
	"""Returns list of batch filepaths covering at least the time range given, but possibly longer.
	May contain multiple results with the same timestamp.
	start and end must be datetimes.
	"""
	# pad start and end to capture neighboring batches, including messages
	# with a wide time range, which might actually be in an even earlier batch.
	start -= timedelta(seconds=2 * BATCH_INTERVAL)
	end += timedelta(seconds=BATCH_INTERVAL)
	for hour_path in hour_paths_for_range(hours_path, start, end):
		hour = os.path.basename(hour_path)
		for name in listdir(hour_path):
			min_sec = name.split("-")[0]
			timestamp = datetime.strptime("{}:{}".format(hour, min_sec), "%Y-%m-%dT%H:%M:%S")
			if start < timestamp < end:
				yield os.path.join(hour_path, name)


@timed("merge_messages", normalize=lambda _, left, right: len(left) + len(right))
def merge_messages(left, right):
	"""Merges two lists of messages into one merged list.
	This operation should be a CRDT, ie. all the following hold:
	- associative: merge(merge(A, B), C) == merge(A, merge(B, C))
	- commutitive: merge(A, B) == merge(B, A)
	- reflexive: merge(A, A) == A
	This means that no matter what order information from different sources
	is incorporated (or if sources are repeated), the results should be the same.
	"""
	# An optimization - if either size is empty, return the other side without processing.
	if not left:
		return right
	if not right:
		return left

	# Calculates intersection of time range of both messages, or None if they don't overlap
	def overlap(a, b):
		range_start = max(a['time'], b['time'])
		range_end = min(a['time'] + a['time_range'], b['time'] + b['time_range'])
		if range_end < range_start:
			return None
		return range_start, range_end - range_start

	# Returns merged message if two messages are compatible with being the same message,
	# or else None.
	def merge_message(a, b):
		o = overlap(a, b)
		if o and all(
			a.get(k) == b.get(k)
			for k in set(a.keys()) | set(b.keys())
			if k not in ("receivers", "time", "time_range")
		):
			receivers = a["receivers"] | b["receivers"]
			# Error checking - make sure no receiver timestamps are being overwritten.
			# This would indicate we're merging two messages recieved at different times
			# by the same recipient.
			for k in receivers.keys():
				for old in (a, b):
					if k in old and old[k] != receivers[k]:
						raise ValueError(f"Merge would merge two messages with different recipient timestamps: {a}, {b}")
			return a | {
				"time": o[0],
				"time_range": o[1],
				"receivers": receivers,
			}
		return None

	# Match things with identical ids first, and collect unmatched into left and right lists
	by_id = {}
	unmatched = [], []
	for messages, u in zip((left, right), unmatched):
		for message in messages:
			id = (message.get('tags') or {}).get('id')
			if id:
				by_id.setdefault(id, []).append(message)
			else:
				u.append(message)

	result = []
	for id, messages in by_id.items():
		if len(messages) == 1:
			logging.debug(f"Message with id {id} has no match")
			result.append(messages[0])
		else:
			merged = merge_message(*messages)
			if merged is None:
				raise ValueError(f"Got two non-matching messages with id {id}: {messages[0]}, {messages[1]}")
			logging.debug(f"Merged messages with id {id}")
			result.append(merged)

	# For time-range messages, pair off each one in left with first match in right,
	# and pass through anything with no matches.
	left_unmatched, right_unmatched = unmatched
	for message in left_unmatched:
		for other in right_unmatched:
			merged = merge_message(message, other)
			if merged:
				logging.debug(
					"Matched {m[command]} message {a[time]}+{a[time_range]} & {b[time]}+{b[time_range]} -> {m[time]}+{m[time_range]}"
					.format(a=message, b=other, m=merged)
				)
				right_unmatched.remove(other)
				result.append(merged)
				break
		else:
			logging.debug("No match found for {m[command]} at {m[time]}+{m[time_range]}".format(m=message))
			result.append(message)
	for message in right_unmatched:
		logging.debug("No match found for {m[command]} at {m[time]}+{m[time_range]}".format(m=message))
		result.append(message)

	return result
