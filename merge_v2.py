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
	if not left:
		return right
	if not right:
		return left

	result = []
	while left and right:
		# Find earliest message out of left and right.
		# The other side becomes the candidate messages.
		if left[0]['time'] <= right[0]['time']:
			message, candidates = left.pop(0), right
		else:
			message, candidates = right.pop(0), left

		# Scan candidates for matching message until found or we know there is no match
		id = message.get("tags", {}).get("id")
		end = message['time'] + message['time_range']
		merged = None
		for index, candidate in enumerate(candidates):
			# optimization: stop when earliest candidate is after message's end time
			if end < candidate['time']:
				break
			if id is None:
				merged = merge_message(message, candidate)
				if merged is not None:
					candidates.pop(index)
					break
			elif candidate.get("tags", {}).get("id") == id:
				merged = merge_message(message, candidate)
				if merged is None:
					raise ValueError("TODO")
				candidates.pop(index)
				break

		# If unmatched, just keep original
		if merged is None:
			merged = message

		result.append(message)

	# Once one side is exhausted, the other side must have all remaining messages unmatched.
	# So just append everything.
	result += left + right

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
