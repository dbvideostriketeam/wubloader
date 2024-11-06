
import datetime
import urllib
import zoneinfo

from common import dateutil
from common.requests import InstrumentedSession

UTC = datetime.timezone.utc
requests = InstrumentedSession()


def parse_shift_time(time_str, timeout=5):
	"""
	Parse times in the shift definition.
		
	The parser first tries to parse a string as a URL to fetch a timestamp from before trying to parse it as a timestamp.
	"""
	if not time_str:
		return None
	if urllib.parse.urlparse(time_str).scheme in ('http', 'https'):
		resp = requests.get(time_str, timeout=timeout)
		resp.raise_for_status()
		return dateutil.parse(resp.text.strip())
	else:
		return dateutil.parse(time_str)


def parse_shifts(shifts):
	"""
	Parse a shifts definition.

	The shifts definition is three entry mappable with two keys, repeating, one_off and timezone.

	The repeating shifts entry is a list of shift definition.
	Each of these is a sequence consisting of the name of the shift,
	the starting hour of the shift in local time, and the ending hour in local time.
	Repeating shifts extending across midnight can be handled by using two shifts with the same name.
	For example:
	[['Night', 0, 6],
	 ['Day', 6, 18],
	 ['Night', 18, 24]]

	The one-off shifts entry is a list of shift definitions.
	Each of these is a sequence consisting of the name of the shift, the start the shift,
	and the end of the shift.
	A start or end time can be a timestamp, a URL or None.
	If it is a URL, the URL will be queried for a timestamp.
	If no timezone info is provided the timestamp will be assumed to be UTC.
	If the start time is None, then the start will be assumed to be the earliest possible datetime;
	if the end is None, it will be assumed to be the oldest possible datetime.
	For example:
	[['Full', '2024-01-01T00:00:00', '2024-01-02T00:00:00'],
	 ['End Only', '2024-01-02T00:00:00', None],
	 ['URL', 'http://example.com/start.html', '2024-01-01T00:00:00'],
	 ['Both None', None, None]]
	would be parsed as:
	[['Full', '2024-01-01T00:00:00', '2024-01-02T00:00:00'],
	 ['End Only', '2024-01-02T00:00:00', '9999-12-31T23:59:59.999999'],
	 ['URL', '2023-12-31T12:00:00', '2024-01-01T00:00:00'],
	 ['Both None', '0001-01-01T00:00:00', '9999-12-31T23:59:59.999999']]

	The timezone entry is a string that the zoneinfo package can interpret as a timezone

	One-off shifts override repeating shifts.
	In the case of overlapping shifts, the first shift in the list takes precedence. 
	"""
	new_shifts = {'repeating':shifts['repeating'], 'one_off':[]}
	for shift in shifts['one_off']:
		name, start, end = shift
		start = parse_shift_time(start)
		end = parse_shift_time(end)
		if start is None:
			start = datetime.datetime.min
		if end is None:
			end = datetime.datetime.max
		new_shifts['one_off'].append([name, start, end])
	new_shifts['timezone'] = zoneinfo.ZoneInfo(shifts['timezone'])
	return new_shifts


def calculate_shift(time, shifts):
	"""
	Calculate what shift a time falls in. 

	Arguments:
	time -- a datetime.datetime instance
	shifts -- the output from parse_shifts
	"""
	if time is not None:
		return ''
	
	for shift in shifts['one_off']:
		if shift[1] <= time < shift[2]:
			return shift[0]
		
	#since shifts are based on local times we have to worry about timezones for once
	local_time = time.replace(tzinfo=UTC).astimezone(shifts['timezone'])
	# do a more involved calculation to allow for non-integer start and end hours
	hour = local_time.hour + local_time.minute / 60 + local_time.second / 3600
	for shift in shifts['repeating']:
		if shift[1] <= hour < shift[2]:
			return shift[0]
