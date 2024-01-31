
import json
import sys

import argh

def encode_ass(sections):
	"""
		Create an ASS text file from an ordered dict of {section name: entries}.
		Each entries value is a list (line type, fields).
		fields is a list of fields, to be comma-seperated.
		Values are NOT escaped, you should ensure you only have allowed characters
		(eg. only use a comma in the final field of a Dialogue).
	"""
	lines = []
	for section, entries in sections.items():
		lines.append(f"[{section}]")
		lines += [
			"{}: {}".format(type, ", ".join(map(str, fields)))
			for type, fields in entries
		]
	return "\n".join(lines)

def encode_time(time):
	hours, time = divmod(time, 3600)
	mins, secs = divmod(time, 60)
	return f"{int(hours)}:{int(mins):02d}:{secs:05.2f}"

def encode_dialogue(start, end, text):
	return ("Dialogue", [encode_time(start), encode_time(end), "Chat", text])

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

def lines_to_dialogue(chat_box, start, end, lines):
	lines = "\\N".join([text for start, text in lines][::-1])
	clip_args = ",".join(map(str, chat_box))
	text = f"{{ \\clip({clip_args}) }}" + lines
	return encode_dialogue(start, end, text)

def gen_dialogues(chat_box, messages, time_base, message_ttl=10):
	window = []
	prev_start = None
	for message in messages:
		next_start, text = message_to_line(message, time_base)
		while window and window[0][0] + message_ttl < next_start:
			end = window[0][0] + message_ttl
			yield lines_to_dialogue(chat_box, prev_start, end, window)
			window.pop(0)
			prev_start = end
		window.append((next_start, text))
		if prev_start is not None:
			yield lines_to_dialogue(chat_box, prev_start, next_start, window)
		prev_start = next_start
	# flush remaining messages
	while window:
		end = window[0][0] + message_ttl
		yield lines_to_dialogue(chat_box, prev_start, end, window)
		window.pop(0)
		prev_start = end

def gen_prelude(title, author, resolution, style_options):
	return {
		"Script Info": [
			("Title", [title]),
			("Original Script", [author]),
			("Script Type", ["V4.00+"]),
			("PlayResX", [resolution[0]]),
			("PlayResY", [resolution[1]]),
		],
		"V4+ Styles": [
			("Format", ["Name"] + list(style_options.keys())),
			("Style", ["Chat"] + list(style_options.values())),
		],
	}

def comma_sep(n, type):
	def parse_comma_sep(s):
		parts = s.split(",")
		if len(parts) != n:
			raise ValueError("Wrong number of parts")
		return list(map(type, parts))

@argh.arg("--pos", metavar="LEFT,TOP,RIGHT,BOTTOM", type=comma_sep(4, int))
@argh.arg("--resolution", metavar="WIDTH,HEIGHT", type=comma_sep(2, int))
def main(
	title,
	time_base=0,
	resolution=(1920, 1080),
	pos=(1220, 100, 1910, 810),
	font_size=40,
	outline_width=1,
	shadow_width=1,
):
	messages = sys.stdin.read().strip().split("\n")
	messages = [json.loads(line) for line in messages]
	ass = gen_prelude(title, "Video Strike Team", (1920, 1080), {
		"Fontsize": font_size,
		"BorderStyle": 1, # outline + shadow
		"Outline": outline_width,
		"Shadow": shadow_width,
		"Alignment": 9, # top-right
		"MarginL": pos[0],
		"MarginR": resolution[0] - pos[2],
		"MarginV": pos[1],
	})
	ass["Events"] = [("Format", ["Start", "End", "Style", "Text"])]
	ass["Events"] += list(gen_dialogues(pos, messages, time_base))
	print(encode_ass(ass))

if __name__ == '__main__':
	argh.dispatch_command(main)
