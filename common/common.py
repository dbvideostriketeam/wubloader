
"""A place for common utilities between wubloader components"""


import datetime

import dateutil.parser
import yaml


class Config(object):
	def load(self,
		run_start_time,
	):
		# PyYAML tries to...ugh...be clever, and parse timestamps if it can work out how.
		# So we should only try to parse if it's not datetime already.
		if not isinstance(run_start_time, datetime.datetime):
			run_start_time = dateutil.parser.parse(run_start_time)
		self.run_start_time = run_start_time


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
