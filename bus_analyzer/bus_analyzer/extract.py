
import os
from io import BytesIO

import argh
from PIL import Image, ImageStat

import common
from common.segments import extract_frame, parse_segment_path


# DB2023 buscam
# bounding box (left x, top y, right x, bottom y) of the area the odometer can be in
ODO_COORDS = 1121, 820, 1270, 897
# starting x coord of each digit within the odo box
DIGIT_X_COORDS = [0, 28, 56, 84, 123]
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
def to_digits(output_dir, paths, box_only=False):
	"""Extracts each digit and saves to a file. Useful for testing or building prototypes."""
	if not os.path.exists(output_dir):
		os.mkdir(output_dir)
	for path in paths:
		name = os.path.splitext(os.path.basename(path))[0]
		image = Image.open(path)
		if not box_only:
			image = extract_odo(image)
		for i, digit in enumerate(extract_digits(image)):
			output_path = os.path.join(output_dir, "{}-digit{}.png".format(name, i))
			digit.save(output_path)


def extract_odo(image):
	"""Takes a full frame, and returns the odo box"""
	return image.crop(ODO_COORDS)


def extract_digits(image, include_last=True):
	"""Takes an odo box, and returns a list of 9x6 digit images"""
	# convert to greyscale
	image = image.convert(mode='L')
	digits = []
	for i, x in enumerate(DIGIT_X_COORDS):
		# last digit is special
		is_last = i == len(DIGIT_X_COORDS) - 1
		if is_last and not include_last:
			continue
		digit = image.crop((x, 0, x + DIGIT_WIDTH, image.height))
		digits.append(normalize_digit(digit, is_last))
	return digits


def normalize_digit(digit, is_last=False):
	# Calculate total brightness by row
	rows = [
		sum(digit.getpixel((x, y)) for x in range(digit.width))
		for y in range(digit.height)
	]
	# Find brightest sub-image of DIGIT_HEIGHT rows
	h = LAST_DIGIT_HEIGHT if is_last else DIGIT_HEIGHT
	start_at = max(range(digit.height - (h-1)), key=lambda y: sum(rows[y:y+h]))
	# Cut image to only be that part
	digit = digit.crop((0, start_at, digit.width, start_at + h))

	# Last digit is inverted - by looking for brightest sub-image we've likely found
	# the section that has a white background. Now we want to normalize that so it looks like
	# other images.
	if is_last:
		digit = digit.point(lambda v: 255 - v)

	# Expand the range of the image so that the darkest pixel becomes black
	# and the lightest becomes white
	_min, _max = digit.getextrema()
	_range = _max - _min
	if _range == 0:
		digit = digit.point(lambda v: 128)
	else:
		digit = digit.point(lambda v: 255 * (v - _min) / _range)
	
	return digit


def recognize_digit(prototypes, image):
	"""Takes a normalized digit image and returns (detected number, score, all_scores)
	where score is between 0 and 1. Higher numbers are more certain the number is correct.
	all_scores is for debugging.
	"""
	scores = sorted([
		(compare_images(prototypes[n], image), n)
		for n in range(10)
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
	return [
		Image.open(os.path.join(prototypes_path, "{}.png".format(n)))
		for n in range(10)
	]


@cli
def read_digit(digit, prototypes_path="./odo-digit-prototypes", verbose=False):
	"""For debugging. Compares an extracted digit image to each prototype and prints scores."""
	prototypes = load_prototypes(prototypes_path)
	digit = Image.open(digit)
	guess, score, all_scores = recognize_digit(prototypes, digit)
	print("Digit = {} with score {}".format(guess, score))
	if verbose:
		all_scores.sort(key=lambda x: x[1])
		for s, n in all_scores:
			print("{}: {}".format(n, s))


def recognize_odometer(prototypes, frame):
	"""Takes a full image frame and returns (detected mile value, score, digits)
	where score is between 0 and 1. Higher numbers are more certain the value is correct.
	digits is for debugging.
	"""
	odo = extract_odo(frame)
	digits = extract_digits(odo, include_last=False)
	digits = [recognize_digit(prototypes, digit) for digit in digits]
	value = sum(digit * 10**i for i, (digit, _, _) in enumerate(digits[::-1]))
	# Use average score of digits as frame score
	score = sum(score for _, score, _ in digits) / len(digits)
	return value, score, digits


@cli
@argh.arg("frames", nargs="+")
def read_frame(frames, prototypes_path="./odo-digit-prototypes", verbose=False, include_last=False):
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
			for guess, score, all_scores in digits:
				print("Digit = {} with score {}".format(guess, score))
		print("{}: {} with score {}".format(filename, value, score))


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


def extract_segment(prototypes, segment):
	# We haven't observed worse than 0.15 or so in the wild,
	# and an all-black screen is identified as "1" with a score of 0.07.
	# So as a rough middle ground, require at least 0.1.
	ODO_SCORE_THRESHOLD = 0.1
	frame_data = b"".join(extract_frame([segment], segment.start))
	frame = Image.open(BytesIO(frame_data))
	odometer, score, _ = recognize_odometer(prototypes, frame)
	return odometer if score >= ODO_SCORE_THRESHOLD else None


if __name__ == '__main__':
	cli()
