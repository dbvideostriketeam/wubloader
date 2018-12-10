
"""A place for common utilities between wubloader components"""


import datetime

import dateutil.parser


def dt_to_bustime(start, dt):
	"""Convert a datetime to bus time. Bus time is seconds since the given start point."""
	return (dt - start).total_seconds()


def bustime_to_dt(start, bustime):
	"""Convert from bus time to a datetime"""
	return start + datetime.timedelta(seconds=bustime)


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
