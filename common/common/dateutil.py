

"""Wrapper code around dateutil to use it more sanely"""


# required so we are able to import dateutil despite this module also being called dateutil
from __future__ import absolute_import

import dateutil.parser
import dateutil.tz


def parse(timestamp):
	"""Parse given timestamp, convert to UTC, and return naive UTC datetime"""
	dt = dateutil.parser.parse(timestamp)
	if dt.tzinfo is not None:
		dt = dt.astimezone(dateutil.tz.tzutc()).replace(tzinfo=None)
	return dt


def parse_utc_only(timestamp):
	"""Parse given timestamp, but assume it's already in UTC and ignore other timezone info"""
	return dateutil.parser.parse(timestamp, ignoretz=True)
