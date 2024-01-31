
import json
import sys

import argh

CHAT_BOX = (1220, 100, 1910, 810)

def encode_time(time):
	hours, time = divmod(time, 3600)
	mins, secs = divmod(time, 60)
	return f"{int(hours)}:{int(mins):02d}:{secs:05.2f}"

def encode_dialogue(start, end, text):
	return f"Dialogue: {encode_time(start)}, {encode_time(end)}, Chat, {text}"

def message_to_line(message, time_base):
	time = message["time"] - time_base
	tags = message.get("tags", {})

	sender = tags.get("display-name")
	if sender is None:
		sender = message["sender"]

	content = message["params"][1]
	if content.startswith("\x01"):
		content = content[1:-1].split(" ", 1)[1]
		text = f"{sender} {content}"
	else:
		text = f"{sender}: {content}"

	color = tags.get("color")
	if color is None:
		color = "FFFFFF"
	else:
		color = color.lstrip("#")
	text = f"{{ \\c&H{color}& }}" + text
	return time, text

def lines_to_dialogue(start, end, lines):
	lines = "\\N".join([text for start, text in lines][::-1])
	clip_args = ",".join(map(str, CHAT_BOX))
	text = f"{{ \\clip({clip_args}) }}" + lines
	return encode_dialogue(start, end, text)

def gen_dialogues(messages, time_base, message_ttl=10):
	window = []
	prev_start = None
	for message in messages:
		next_start, text = message_to_line(message, time_base)
		while window and window[0][0] + message_ttl < next_start:
			end = window[0][0] + message_ttl
			yield lines_to_dialogue(prev_start, end, window)
			window.pop(0)
			prev_start = end
		window.append((next_start, text))
		if prev_start is not None:
			yield lines_to_dialogue(prev_start, next_start, window)
		prev_start = next_start
	# flush remaining messages
	while window:
		end = window[0][0] + message_ttl
		yield lines_to_dialogue(prev_start, end, window)
		window.pop(0)
		prev_start = end

def main(time_base=0):
	messages = sys.stdin.read().strip().split("\n")
	messages = [json.loads(line) for line in messages]
	for dialogue in gen_dialogues(messages, time_base):
		print(dialogue)

if __name__ == '__main__':
	argh.dispatch_command(main)
