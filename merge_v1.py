import json
import time
import hashlib

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


def merge_messages(left, right):
	# An optimization - if either size is empty, return the other side without processing.
	if not left:
		return right
	if not right:
		return left

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
			result.append(messages[0])
		else:
			merged = merge_message(*messages)
			if merged is None:
				raise ValueError(f"Got two non-matching messages with id {id}: {messages[0]}, {messages[1]}")
			result.append(merged)

	# For time-range messages, pair off each one in left with first match in right,
	# and pass through anything with no matches.
	left_unmatched, right_unmatched = unmatched
	for message in left_unmatched:
		for other in right_unmatched:
			merged = merge_message(message, other)
			if merged:
				right_unmatched.remove(other)
				result.append(merged)
				break
		else:
			result.append(message)
	for message in right_unmatched:
		result.append(message)

	return result


def main(*files):
	batches = [json.load(open(file)) for file in files]
	result = batches[0]
	start = time.monotonic()
	for batch in batches[1:]:
		result = merge_messages(result, batch)
	interval = time.monotonic() - start
	hash = hashlib.sha256(json.dumps(result).encode()).hexdigest()
	print(f"Merged {len(batches)} batches in {interval:.3f}s to hash {hash}")

if __name__ == '__main__':
	import sys
	main(*sys.argv[1:])
