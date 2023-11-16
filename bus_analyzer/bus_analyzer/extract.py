
import os
from io import BytesIO

import argh
from PIL import Image

import common
from common.segments import extract_frame, parse_segment_path


# DB2023 buscam
# bounding box (left x, top y, right x, bottom y) of the area the odometer can be in
AREA_COORDS = {
	"odo": (1121, 820, 1270, 897),
	"clock": (1685, 819, 1804, 877),
}
# starting x coord of each digit within the odo box
DIGIT_X_COORDS = {
	"odo": [0, 28, 56, 84, 123],
	"clock": [0, 27, 66, 93],
}
# value of each digit
DIGIT_BASES = {
	"odo": [1000, 100, 10, 1, 0.1],
	"clock": [600, 60, 10, 1],
}

DIGIT_WIDTH = 26
# Most digits we only care about the actual character height
DIGIT_HEIGHT = 26
# But last digit we want the full white-background area as we want to try to match
# based on position also.
LAST_DIGIT_HEIGHT = 38

# get back py2 zip behaviour
_zip = zip
def zip(*args):
	return list(_zip(*args))


cli = argh.EntryPoint()

@cli
@argh.arg("paths", nargs="+")
def to_digits(output_dir, paths, box_only=False, type="odo"):
	"""Extracts each digit and saves to a file. Useful for testing or building prototypes."""
	if not os.path.exists(output_dir):
		os.mkdir(output_dir)
	for path in paths:
		name = os.path.splitext(os.path.basename(path))[0]
		image = Image.open(path)
		if not box_only:
			image = image.crop(AREA_COORDS[type])
		for i, digit in enumerate(extract_digits(image, type)):
			output_path = os.path.join(output_dir, "{}-digit{}.png".format(name, i))
			digit.save(output_path)


def get_brightest_region(image, xs, height):
	"""For given image, return the sub-image of given height with the brightest
	values for all the pixels at given x positions within the row."""
	# Calculate total brightness by row
	rows = [
		sum(image.getpixel((x, y)) for x in xs)
		for y in range(image.height)
	]
	# Find brightest sub-image of `height` rows
	start_at = max(range(image.height - (height-1)), key=lambda y: sum(rows[y:y+height]))
	# Cut image to only be that part
	return image.crop((0, start_at, image.width, start_at + height))


def get_green(image):
	"""Given a RGB image, highlight "green" areas and return a monochrome image"""
	data = image.getdata()
	newdata = [g - max(r, b) for r, g, b in data]
	newimage = Image.new("L", image.size)
	newimage.putdata(newdata)
	return newimage


def extract_digits(image, type):
	"""Takes an odo box, and returns a list of digit images"""
	main_digit_coords = DIGIT_X_COORDS[type]
	if type == "odo":
		main_digit_coords = main_digit_coords[:-1]

	# convert to greyscale, possibly only on green channel
	if type == "clock":
		image = get_green(image)
	else:
		image = image.convert(mode='L')

	# Find main digits y position
	digit_xs = [
		x + dx
		for x in DIGIT_X_COORDS[type]
		for dx in range(DIGIT_WIDTH)
	]
	main_digits = get_brightest_region(image, digit_xs, DIGIT_HEIGHT)
	main_digits = normalize(main_digits)

	digits = []
	for i, x in enumerate(main_digit_coords):
		digit = main_digits.crop((x, 0, x + DIGIT_WIDTH, main_digits.height))
		digits.append(digit)

	if type == "odo":
		x = DIGIT_X_COORDS["odo"][-1]
		last_digit = get_brightest_region(image, range(x, x + DIGIT_WIDTH), LAST_DIGIT_HEIGHT)
		last_digit = last_digit.crop((x, 0, x + DIGIT_WIDTH, last_digit.height))
		last_digit = normalize(last_digit)
		digits.append(last_digit)

	return digits


def normalize(image):
	# Expand the range of the image so that the darkest pixel becomes black
	# and the lightest becomes white
	_min, _max = image.getextrema()
	_range = _max - _min
	if _range == 0:
		image = image.point(lambda v: 128)
	else:
		image = image.point(lambda v: 255 * (v - _min) / _range)
	
	return image


def recognize_digit(prototypes, image, blank_is_zero=False):
	"""Takes a normalized digit image and returns (detected number, score, all_scores)
	where score is between 0 and 1. Higher numbers are more certain the number is correct.
	all_scores is for debugging.
	If the most likely detection is NOT a number, None is returned instead.
	"""
	def maybeFloat(n):
		if n == "blank" and blank_is_zero:
			return 0
		try:
			return float(n)
		except ValueError:
			return None
	scores = sorted([
		(compare_images(prototype, image), maybeFloat(n))
		for n, prototype in prototypes.items()
	], reverse=True)
	best_score, number = scores[0]
	runner_up_score, _ = scores[1]
	# we penalize score if the second best score is high, as this indicates we're uncertain
	# which number it is even though both match.
	return number, best_score - runner_up_score, scores


def compare_images(prototype, image):
	"""Takes a normalized digit image and a prototype image, and returns a score
	for how close the image is to looking like that prototype."""
	pairs = zip(image.getdata(), prototype.getdata())
	error_squared = sum((a - b)**2 for a, b in pairs)
	MAX_ERROR_SQUARED = 255**2 * len(pairs)
	return 1 - (float(error_squared) / MAX_ERROR_SQUARED)**0.5


def load_prototypes(prototypes_path):
	prototypes = {}
	for kind in os.listdir(prototypes_path):
		prototypes[kind] = {}
		path = os.path.join(prototypes_path, kind)
		for filename in os.listdir(path):
			if not filename.endswith(".png"):
				continue
			name = filename[:-4]
			prototypes[kind][name] = Image.open(os.path.join(path, filename))
	return prototypes


@cli
def read_digit(digit, prototypes_path="./prototypes", verbose=False):
	"""For debugging. Compares an extracted digit image to each prototype and prints scores."""
	prototypes = load_prototypes(prototypes_path)
	digit = Image.open(digit)
	guess, score, all_scores = recognize_digit(prototypes["odo-digits"], digit)
	print("Digit = {} with score {}".format(guess, score))
	if verbose:
		all_scores.sort(key=lambda x: -1 if x[1] is None else x[1])
		for s, n in all_scores:
			print("{}: {}".format(n, s))


def recognize_odometer(prototypes, frame):
	"""Takes a full image frame and returns (detected mile value, score, digits)
	where score is between 0 and 1. Higher numbers are more certain the value is correct.
	digits is for debugging.
	"""
	odo = frame.crop(AREA_COORDS["odo"])
	digits = extract_digits(odo, "odo")
	digits = [
		recognize_digit(prototypes["odo-digits"], digit) for digit in digits[:-1]
	] + [
		recognize_digit(prototypes["odo-last-digit"], digits[-1])
	]
	# If any digit is None, report whole thing as None. Otherwise, calculate the number.
	if any(digit is None for digit, _, _ in digits):
		value = None
	else:
		value = sum(digit * base for base, (digit, _, _) in zip(DIGIT_BASES["odo"], digits))
	# Use average score of digits as frame score
	score = sum(score for _, score, _ in digits) / len(digits)
	return value, score, digits


def recognize_clock(prototypes, frame):
	clock = frame.crop(AREA_COORDS["clock"])
	digits = extract_digits(clock, "clock")
	digits = [
		recognize_digit(prototypes["odo-digits"], digit, i == 0) for i, digit in enumerate(digits)
	]
	if any(digit is None for digit, _, _ in digits):
		# If any digit is None, report whole thing as None
		value = None
	elif digits[0][0] not in range(2):
		# 1st digit is 0-1, or else fail
		value = None
	elif digits[2][0] not in range(6):
		# 3rd digit is 0-5, or else fail
		value = None
	else:
		value = sum(digit * base for base, (digit, _, _) in zip(DIGIT_BASES["clock"], digits))
	# Use average score of digits as frame score
	score = sum(score for _, score, _ in digits) / len(digits)
	return value, score, digits


@cli
@argh.arg("frames", nargs="+")
def read_frame(frames, prototypes_path="./prototypes", verbose=False):
	"""For testing. Takes any number of frame images (or segments) and prints the odometer reading."""
	prototypes = load_prototypes(prototypes_path)
	for filename in frames:
		if filename.endswith(".ts"):
			segment = parse_segment_path(filename)
			frame_data = b"".join(extract_frame([segment], segment.start))
			frame = Image.open(BytesIO(frame_data))
		else:
			frame = Image.open(filename)

		value, score, digits = recognize_odometer(prototypes, frame)
		if verbose:
			for guess, _score, all_scores in digits:
				print("Digit = {} with score {}".format(guess, _score))
		print("{}: odo {} with score {}".format(filename, value, score))

		value, score, digits = recognize_clock(prototypes, frame)
		if verbose:
			for guess, _score, all_scores in digits:
				print("Digit = {} with score {}".format(guess, _score))
		print("{}: clock {} with score {}".format(filename, value, score))

		value, score, all_scores = recognize_time_of_day(frame)
		if verbose:
			for color, _score in all_scores:
				print("{}: {}".format(color, _score))
		print("{}: time-of-day {} with score {}".format(filename, value, score))


@cli
def create_prototype(output, *images):
	"""Create a prototype image by averaging all the given images"""
	first = Image.open(images[0])
	data = list(first.getdata())
	for image in images[1:]:
		image = Image.open(image)
		for i, value in enumerate(image.getdata()):
			data[i] += value
	data = [v / len(images) for v in data]
	first.putdata(data)
	first.save(output)


@cli
def get_frame(*segments):
	for path in segments:
		segment = parse_segment_path(path)
		filename = segment.start.strftime("%Y-%m-%dT-%H-%M-%S") + ".png"
		with open(filename, "wb") as f:
			for chunk in extract_frame([segment], segment.start):
				common.writeall(f.write, chunk)
		print(filename)


def compare_colors(color_a, color_b):
	MAX_ERROR_SQUARED = 255**2 * len(color_a)
	return 1 - float(sum((a - b)**2 for a, b in zip(color_a, color_b))) / MAX_ERROR_SQUARED


def recognize_time_of_day(frame):
	"""Returns time of day, score, all scores."""
	COLORS = {
		"day": (89, 236, 239),
		"dusk": (199, 162, 205),
		"night": (1, 1, 1),
		"dawn": (51, 59, 142),
	}
	sample = frame.getpixel((177, 255))
	scores = [
		(tod, compare_colors(sample, color))
		for tod, color in COLORS.items()
	]
	best, score = max(scores, key=lambda t: t[1])
	return best, score, scores


def extract_segment(prototypes, segment):
	ODO_SCORE_THRESHOLD = 0.01
	CLOCK_SCORE_THRESHOLD = 0.01
	TOD_SCORE_THRESHOLD = 0.9
	frame_data = b"".join(extract_frame([segment], segment.start))
	frame = Image.open(BytesIO(frame_data))
	odometer, score, _ = recognize_odometer(prototypes, frame)
	if score < ODO_SCORE_THRESHOLD:
		odometer = None
	clock, score, _ = recognize_clock(prototypes, frame)
	if score < CLOCK_SCORE_THRESHOLD:
		clock = None
	tod, score, _ = recognize_time_of_day(frame)
	if score < TOD_SCORE_THRESHOLD:
		tod = None
	return odometer, clock, tod


if __name__ == '__main__':
	cli()
