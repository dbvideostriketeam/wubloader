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

def merge_messages(*batches):
	batches = [b for b in batches if len(b) > 0]

	result = []
	while len(batches) > 1:
		# Shortcut for non-overlapping time ranges - if one batch has messages that end before
		# the start of any other batch, take those messages directly without trying to match them.

		# Find batches with the earliest and second earliest messages
		first = batches[0]
		second = batches[1]
		if first[0]["time"] > second[0]["time"]:
			first, second = second, first
		for batch in batches[2:]:
			if batch[0]["time"] < first[0]["time"]:
				first, second = batch, first
			elif batch[0]["time"] < second[0]["time"]:
				second = batch

		# Find messages in first batch that end before the start of second batch,
		# and copy them directly to result.
		cutoff = second[0]["time"]
		while first and first[0]["time"] + first[0]["time_range"] < cutoff:
			result.append(first[0])
			first.pop(0)

		# If first now overlaps with second, move on to try to find messages to merge.
		# If no overlap (either first is exhausted, or second now starts sooner than first)
		# then just start again from the top and look for more non-overapping ranges.
		if not first:
			batches.remove(first)
			continue
		if cutoff < first[0]["time"]:
			continue

		message = first.pop(0)
		id = (message.get("tags") or {}).get("id")

		# For each other batch, attempt to find a matching message
		for batch in batches:
			if batch is first:
				continue
			end = message["time"] + message["time_range"]
			merged = None
			for index, candidate in enumerate(batch):
				# optimization: stop when earliest candidate is after message's end time
				if end < candidate['time']:
					break
				if id is None:
					merged = merge_message(message, candidate)
					if merged is not None:
						batch.pop(index)
						break
				elif (candidate.get("tags") or {}).get("id") == id:
					merged = merge_message(message, candidate)
					if merged is None:
						raise ValueError("TODO")
					batch.pop(index)
					break
			if merged is not None:
				message = merged

		result.append(message)
		batches = [b for b in batches if len(b) > 0]

	# Once all but one batch is exhausted, the last one must have all remaining messages unmatched.
	# So just append everything.
	if batches:
		result += batches[0]

	return result


def load(file):
	with open(file) as f:
		return [json.loads(line) for line in f.read().strip().split("\n")]


def main(*files):
	out = False
	if files and files[0] == "--out":
		files = files[1:]
		out = True
	batches = [load(file) for file in files]
	start = time.monotonic()
	result = merge_messages(*batches)
	interval = time.monotonic() - start
	if out:
		print(json.dumps(result))
	else:
		hash = hashlib.sha256(json.dumps(result).encode()).hexdigest()
		print(f"Merged {len(batches)} batches in {interval:.3f}s to hash {hash}")

if __name__ == '__main__':
	import sys
	main(*sys.argv[1:])
