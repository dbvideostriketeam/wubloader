
"""A place for common utilities between wubloader components"""


import datetime
import errno
import os
import random

from .segments import get_best_segments, fast_cut_segments, full_cut_segments, parse_segment_path, SegmentInfo
from .stats import timed, PromLogCountsHandler, install_stacksampler


def dt_to_bustime(start, dt):
	"""Convert a datetime to bus time. Bus time is seconds since the given start point."""
	return (dt - start).total_seconds()


def bustime_to_dt(start, bustime):
	"""Convert from bus time to a datetime"""
	return start + datetime.timedelta(seconds=bustime)


def parse_bustime(bustime):
	"""Convert from bus time human-readable string [-]HH:MM[:SS[.fff]]
	to float seconds since bustime 00:00. Inverse of format_bustime(),
	see it for detail."""
	if bustime.startswith('-'):
		# parse without the -, then negate it
		return -parse_bustime(bustime[1:])

	parts = bustime.strip().split(':')
	if len(parts) == 2:
		hours, mins = parts
		secs = 0
	elif len(parts) == 3:
		hours, mins, secs = parts
	else:
		raise ValueError("Invalid bustime: must be HH:MM[:SS]")
	hours = int(hours)
	mins = int(mins)
	secs = float(secs)
	return 3600 * hours + 60 * mins + secs


def format_bustime(bustime, round="millisecond"):
	"""Convert bustime to a human-readable string (-)HH:MM:SS.fff, with the
	ending cut off depending on the value of round:
		"millisecond": (default) Round to the nearest millisecond.
		"second": Round down to the current second.
		"minute": Round down to the current minute.
	Examples:
		00:00:00.000
		01:23:00
		110:50
		159:59:59.999
		-10:30:01.100
	Negative times are formatted as time-until-start, preceeded by a minus
	sign.
	eg. "-1:20:00" indicates the run begins in 80 minutes.
	"""
	sign = ''
	if bustime < 0:
		sign = '-'
		bustime = -bustime
	total_mins, secs = divmod(bustime, 60)
	hours, mins = divmod(total_mins, 60)
	parts = [
		"{:02d}".format(int(hours)),
		"{:02d}".format(int(mins)),
	]
	if round == "minute":
		pass
	elif round == "second":
		parts.append("{:02d}".format(int(secs)))
	elif round == "millisecond":
		parts.append("{:06.3f}".format(secs))
	else:
		raise ValueError("Bad rounding value: {!r}".format(round))
	return sign + ":".join(parts)


def rename(old, new):
	"""Atomic rename that succeeds if the target already exists, since we're naming everything
	by hash anyway, so if the filepath already exists the file itself is already there.
	In this case, we delete the source file.
	"""
	try:
		os.rename(old, new)
	except OSError as e:
		if e.errno != errno.EEXIST:
			raise
		os.remove(old)


def ensure_directory(path):
	"""Create directory that contains path, as well as any parent directories,
	if they don't already exist."""
	dir_path = os.path.dirname(path)
	if os.path.exists(dir_path):
		return
	ensure_directory(dir_path)
	try:
		os.mkdir(dir_path)
	except OSError as e:
		# Ignore if EEXISTS. This is needed to avoid a race if two getters run at once.
		if e.errno != errno.EEXIST:
			raise


def jitter(interval):
	"""Apply some 'jitter' to an interval. This is a random +/- 10% change in order to
	smooth out patterns and prevent everything from retrying at the same time.
	"""
	return interval * (0.9 + 0.2 * random.random())


def encode_strings(o):
	"""Recurvisely handles unicode in json output."""
	if isinstance(o, list):
		return [encode_strings(x) for x in o]
	if isinstance(o, dict):
		return {k.encode('utf-8'): encode_strings(v) for k, v in o.items()}
	if isinstance(o, unicode):
		return o.encode('utf-8')
	return o
