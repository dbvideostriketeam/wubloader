
"""A place for common utilities between wubloader components"""
import datetime
import errno
import logging
import os
import random
from signal import SIGTERM
from uuid import uuid4

import gevent.event

from .segments import get_best_segments, rough_cut_segments, fast_cut_segments, full_cut_segments, parse_segment_path, SegmentInfo
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
		secs = "0"
	elif len(parts) == 3:
		hours, mins, secs = parts
	else:
		raise ValueError("Invalid bustime: must be HH:MM[:SS]")

	# Reject negative times. Any negative hours should have been removed by now,
	# and we in particular want to reject negative minutes.
	if any(part.startswith("-") for part in (hours, mins, secs)):
		raise ValueError("Invalid bustime: Individual parts cannot be negative")

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
	os.makedirs(dir_path, exist_ok=True)


def jitter(interval):
	"""Apply some 'jitter' to an interval. This is a random +/- 10% change in order to
	smooth out patterns and prevent everything from retrying at the same time.
	"""
	return interval * (0.9 + 0.2 * random.random())


def writeall(write, value):
	"""Helper for writing a complete string to a file-like object.
	Pass the write function and the value to write, and it will loop if needed to ensure
	all data is written.
	Works for both text and binary files, as long as you pass the right value type for
	the write function.
	"""
	while value:
		n = write(value)
		if n is None:
			# The write func doesn't return the amount written, assume it always writes everything
			break
		if n == 0:
			# This would cause an infinite loop...blow up instead so it's clear what the problem is
			raise Exception("Wrote 0 chars while calling {} with {}-char {}".format(write, len(value), type(value).__name__))
		# remove the first n chars and go again if we have anything left
		value = value[n:]


def atomic_write(filepath, content):
	"""Writes content to filepath atomically, ie. replacing the file in one step
	without potential for partial write. content may be str or bytes.
	If the file already exists, it will silently do nothing as it is assumed a given
	filename can only ever contain the same content.
	"""
	if isinstance(content, str):
		content = content.encode("utf-8")
	temp_path = "{}.{}.temp".format(filepath, uuid4())
	ensure_directory(filepath)
	with open(temp_path, 'wb') as f:
		writeall(f.write, content)
	rename(temp_path, filepath)


def serve_with_graceful_shutdown(server, stop_timeout=20):
	"""Takes a gevent.WSGIServer and serves forever until SIGTERM is received,
	or the server errors. This is slightly tricky to do due to race conditions
	between server.stop() and server.start().
	In particular if start() is called after stop(), then the server will not be stopped.
	To be safe, we must set up our own flag indicating we should stop, and ensure that
	start() has fully completed before we call stop().
	"""
	stopping = gevent.event.Event()
	def stop():
		logging.debug("Stop flag set")
		stopping.set()
	gevent.signal_handler(SIGTERM, stop)

	logging.info("Starting up")
	server.start()
	logging.debug("Started")

	stopping.wait()
	logging.info("Shutting down")
	server.stop(stop_timeout)
	logging.info("Gracefully shut down")


def listdir(path):
	"""as os.listdir but return [] if dir doesn't exist"""
	try:
		return os.listdir(path)
	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		return []
