
"""A place for common utilities between wubloader components"""


import datetime

import dateutil.parser
import yaml


class Config(object):
	def load(self,
		run_start_time,
	):
		self.run_start_time = dateutil.parser.parse(run_start_time)


CONF = Config()


def load_config(path="/etc/wubloader.yaml"):
	with open(path) as f:
		CONF.load(**yaml.safe_load(f))


def dt_to_bustime(dt):
	"""Convert a datetime to bus time. Bus time is seconds since the start of the run
	as defined in the config file."""
	return (dt - CONF.run_start_time).total_seconds()


def bustime_to_dt(bustime):
	"""Convert from bus time to a datetime"""
	return CONF.run_start_time + datetime.timedelta(seconds=bustime)


def format_bustime(bustime, round="millisecond"):
	"""Convert bustime to a human-readable string (-)H:MM:SS.fff, with the
	ending cut off depending on the value of round:
		"millisecond": (default) Round to the nearest millisecond.
		"second": Round down to the current second.
		"minute": Round down to the current minute.
	Examples:
		0:00:00.000
		1:23:00
		110:50
		159:59:59.999
		-10:30:01.100
	Note that a negative value only indicates the number of hours after the start
	is negative, the number of minutes/seconds is simply time past the hour.
	eg. the bustime "-1:20:00" indicates the run begins in 40 minutes, not 80 minutes.
	"""
	whole_secs, fractional = divmod(bustime, 1)
	total_mins, secs = divmod(whole_secs, 60)
	hours, mins = divmod(total_mins, 60)
	parts = "{}:{:02d}:{:02d}:{:.3f}".format(hours, mins, secs, fractional).split(":")
	if round == "millisecond":
		pass
	elif round == "second":
		parts = parts[:-1]
	elif round == "minute":
		parts = parts[:-2]
	else:
		raise ValueError("Bad rounding value: {!r}".format(round))
	return ":".join(parts)
