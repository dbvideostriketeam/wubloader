
"""A place for common utilities between wubloader components"""


import base64
import datetime
import errno
import functools
import itertools
import logging
import os
import random
import sys
from collections import namedtuple

import dateutil.parser
import prometheus_client as prom
from monotonic import monotonic


def timed(name=None,
	buckets=[10.**x for x in range(-9, 5)], normalized_buckets=None,
	normalize=None,
	**labels
):
	"""Decorator that instruments wrapped function to record real, user and system time
	as a prometheus histogram.

	Metrics are recorded as NAME_latency, NAME_cputime{type=user} and NAME_cputime{type=system}
	respectively. User and system time are process-wide (which means they'll be largely meaningless
	if you're using gevent and the wrapped function blocks) and do not include subprocesses.

	NAME defaults to the wrapped function's name.

	Any labels passed in are included. Given label values may be callable, in which case
	they are passed the input and result from the wrapped function and should return a label value.
	Otherwise the given label value is used directly. All label values are automatically str()'d.

	In addition, the "error" label is automatically included, and set to "" if no exception
	occurs, or the name of the exception type if one does.

	The normalize argument, if given, causes the creation of a second set of metrics
	NAME_normalized_latency, etc. The normalize argument should be a callable which
	takes the input and result of the wrapped function and returns a normalization factor.
	All normalized metrics divide the observed times by this factor.
	The intent is to allow a function which is expected to take longer given a larger input
	to be timed on a per-input basis.
	As a special case, when normalize returns 0 or None, normalized metrics are not updated.

	The buckets kwarg is as per prometheus_client.Histogram. The default is a conservative
	but sparse range covering nanoseconds to hours.
	The normalized_buckets kwarg applies to the normalized metrics, and defaults to the same
	as buckets.

	All callables that take inputs and result take them as follows: The first arg is the result,
	followed by *args and **kwargs as per the function's inputs.
	If the wrapped function errored, result is None.
	To simplify error handling in these functions, any errors are taken to mean None,
	and None is interpreted as '' for label values.

	Contrived Example:
		@timed("scanner",
			# constant label
			foo="my example label",
			# label dependent on input
			all=lambda results, predicate, list, find_all=False: find_all,
			# label dependent on output
			found=lambda results, *a, **k: len(found) > 0,
			# normalized on input
			normalize=lambda results, predicate, list, **k: len(list),
		)
		def scanner(predicate, list, find_all=False):
			results = []
			for item in list:
				if predicate(item):
					results.append(item)
					if not find_all:
						break
			return results
	"""

	if normalized_buckets is None:
		normalized_buckets = buckets
	# convert constant (non-callable) values into callables for consistency
	labels = {
		# there's a pyflakes bug here suggesting that v is undefined, but it isn't
		k: v if callable(v) else (lambda *a, **k: v)
		for k, v in labels.items()
	}

	def _timed(fn):
		# can't safely assign to name inside closure, we use a new _name variable instead
		_name = fn.__name__ if name is None else name

		latency = prom.Histogram(
			"{}_latency".format(_name),
			"Wall clock time taken to execute {}".format(_name),
			labels.keys() + ['error'],
			buckets=buckets,
		)
		cputime = prom.Histogram(
			"{}_cputime".format(_name),
			"Process-wide consumed CPU time during execution of {}".format(_name),
			labels.keys() + ['error', 'type'],
			buckets=buckets,
		)
		if normalize:
			normal_latency = prom.Histogram(
				"{}_latency_normalized".format(_name),
				"Wall clock time taken to execute {} per unit of work".format(_name),
				labels.keys() + ['error'],
				buckets=normalized_buckets,
			)
			normal_cputime = prom.Histogram(
				"{}_cputime_normalized".format(_name),
				"Process-wide consumed CPU time during execution of {} per unit of work".format(_name),
				labels.keys() + ['error', 'type'],
				buckets=normalized_buckets,
			)

		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			start_monotonic = monotonic()
			start_user, start_sys, _, _, _ = os.times()

			try:
				ret = fn(*args, **kwargs)
			except Exception:
				ret = None
				error_type, error, tb = sys.exc_info()
			else:
				error = None

			end_monotonic = monotonic()
			end_user, end_sys, _, _, _ = os.times()
			wall_time = end_monotonic - start_monotonic
			user_time = end_user - start_user
			sys_time = end_sys - start_sys

			label_values = {}
			for k, v in labels.items():
				try:
					value = v(ret, *args, **kwargs)
				except Exception:
					value = None
				label_values[k] = '' if value is None else str(value)
			label_values.update(error='' if error is None else type(error).__name__)

			latency.labels(**label_values).observe(wall_time)
			cputime.labels(type='user', **label_values).observe(user_time)
			cputime.labels(type='system', **label_values).observe(sys_time)
			if normalize:
				try:
					factor = normalize(ret, *args, **kwargs)
				except Exception:
					factor = None
				if factor is not None and factor > 0:
					normal_latency.labels(**label_values).observe(wall_time / factor)
					normal_cputime.labels(type='user', **label_values).observe(user_time / factor)
					normal_cputime.labels(type='system', **label_values).observe(sys_time / factor)

			if error is None:
				return ret
			raise error_type, error, tb # re-raise error with original traceback

		return wrapper

	return _timed


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


def unpadded_b64_decode(s):
	"""Decode base64-encoded string that has had its padding removed"""
	# right-pad with '=' to multiple of 4
	s = s + '=' * (- len(s) % 4)
	return base64.b64decode(s, "-_")


class SegmentInfo(
	namedtuple('SegmentInfoBase', [
		'path', 'stream', 'variant', 'start', 'duration', 'is_partial', 'hash'
	])
):
	"""Info parsed from a segment path, including original path.
	Note that start time is a datetime and duration is a timedelta, and hash is a decoded binary string."""
	@property
	def end(self):
		return self.start + self.duration


def parse_segment_path(path):
	"""Parse segment path, returning a SegmentInfo. If path is only the trailing part,
	eg. just a filename, it will leave unknown fields as None."""
	parts = path.split('/')
	# left-pad parts with None up to 4 parts
	parts = [None] * (4 - len(parts)) + parts
	# pull info out of path parts
	stream, variant, hour, filename = parts[-4:]
	# split filename, which should be TIME-DURATION-TYPE-HASH.ts
	try:
		if not filename.endswith('.ts'):
			raise ValueError("Does not end in .ts")
		filename = filename[:-len('.ts')] # chop off .ts
		parts = filename.split('-', 3)
		if len(parts) != 4:
			raise ValueError("Not enough dashes in filename")
		time, duration, type, hash = parts
		if type not in ('full', 'partial'):
			raise ValueError("Unknown type {!r}".format(type))
		return SegmentInfo(
			path = path,
			stream = stream,
			variant = variant,
			start = dateutil.parser.parse("{}:{}".format(hour, time)),
			duration = datetime.timedelta(seconds=float(duration)),
			is_partial = type == "partial",
			hash = unpadded_b64_decode(hash),
		)
	except ValueError as e:
		# wrap error but preserve original traceback
		_, _, tb = sys.exc_info()
		raise ValueError, ValueError("Bad path {!r}: {}".format(path, e)), tb


@timed(
	hours_path=lambda ret, hours_path, start, end: hours_path,
	has_holes=lambda ret, hours_path, start, end: None in ret,
	normalize=lambda ret, hours_path, start, end: len([x for x in ret if x is not None]),
)
def get_best_segments(hours_path, start, end):
	"""Return a list of the best sequence of non-overlapping segments
	we have for a given time range. Hours path should be the directory containing hour directories.
	Time args start and end should be given as datetime objects.
	The first segment may start before the time range, and the last may end after it.
	The returned list contains items that are either:
		SegmentInfo: a segment
		None: represents a discontinuity between the previous segment and the next one.
	ie. as long as two segments appear next to each other, we guarentee there is no gap between
	them, the second one starts right as the first one finishes.
	Similarly, unless the first item is None, the first segment starts <= the start of the time
	range, and unless the last item is None, the last segment ends >= the end of the time range.
	Example:
		Suppose you ask for a time range from 10 to 60. We have 10-second segments covering
		the following times:
			5 to 15
			15 to 25
			30 to 40
			40 to 50
		Then the output would look like:
			segment from 5 to 15
			segment from 15 to 25
			None, as the previous segment ends 5sec before the next one begins
			segment from 30 to 40
			segment from 40 to 50
			None, as the previous segment ends 10sec before the requested end time of 60.
	Note that any is_partial=True segment will be followed by a None, since we can't guarentee
	it joins on to the next segment fully intact.
	"""
	# Note: The exact equality checks in this function are not vulnerable to floating point error,
	# but only because all input dates and durations are only precise to the millisecond, and
	# python's datetime types represent these as integer microseconds internally. So the parsing
	# to these types is exact, and all operations on them are exact, so all operations are exact.

	result = []

	for hour in hour_paths_for_range(hours_path, start, end):
		# best_segments_by_start will give us the best available segment for each unique start time
		for segment in best_segments_by_start(hour):

			# special case: first segment
			if not result:
				# first segment is allowed to be before start as long as it includes it
				if segment.start <= start < segment.end:
					# segment covers start
					result.append(segment)
				elif start < segment.start < end:
					# segment is after start (but before end), so there was no segment that covers start
					# so we begin with a None
					result.append(None)
					result.append(segment)
				else:
					# segment is before start, and doesn't cover start, or starts after end.
					# ignore and go to next.
					continue
			else:
				# normal case: check against previous segment end time
				prev_end = result[-1].end
				if segment.start < prev_end:
					# Overlap! This shouldn't happen, though it might be possible due to weirdness
					# if the stream drops then starts again quickly. We simply ignore the overlapping
					# segment and let the algorithm continue.
					logging.warning("Overlapping segments: {} overlaps end of {}".format(segment, result[-1]))
					continue
				if result[-1].is_partial or prev_end < segment.start:
					# there's a gap between prev end and this start, so add a None
					result.append(None)
				result.append(segment)

			# check if we've reached the end
			if end <= segment.end:
				break

		# this is a weird little construct that says "if we broke from the inner loop,
		# then also break from the outer one. otherwise continue."
		else:
			continue
		break

	# check if we need a trailing None because last segment is partial or doesn't reach end
	if result and (result[-1].is_partial or result[-1].end < end):
		result.append(None)

	return result


def hour_paths_for_range(hours_path, start, end):
	"""Generate a list of hour paths to check when looking for segments between start and end."""
	# truncate start and end to the hour
	def truncate(dt):
		return dt.replace(microsecond=0, second=0, minute=0)
	current = truncate(start)
	end = truncate(end)
	# Begin in the hour prior to start, as there may be a segment that starts in that hour
	# but contains the start time, eg. if the start time is 01:00:01 and there's a segment
	# at 00:59:59 which goes for 3 seconds.
	# Checking the entire hour when in most cases it won't be needed is wasteful, but it's also
	# pretty quick and the complexity of only checking this case when needed just isn't worth it.
	current -= datetime.timedelta(hours=1)
	while current <= end:
		yield os.path.join(hours_path, current.strftime("%Y-%m-%dT%H"))
		current += datetime.timedelta(hours=1)


def best_segments_by_start(hour):
	"""Within a given hour path, yield the "best" segment per unique segment start time.
	Best is defined as non-partial, or failing that the longest partial.
	Note this means this function may perform os.stat()s in order to find the longest partial.
	"""
	try:
		segment_paths = os.listdir(hour)
	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		# path does not exist, treat it as having no files
		return
	segment_paths.sort()
	# note we only parse them as we need them, which is unlikely to save us much time overall
	# but is easy enough to do, so we might as well.
	parsed = (parse_segment_path(os.path.join(hour, name)) for name in segment_paths)
	for start_time, segments in itertools.groupby(parsed, key=lambda segment: segment.start):
		segments = list(segments)
		full_segments = [segment for segment in segments if not segment.is_partial]
		if full_segments:
			if len(full_segments) != 1:
				logging.warning("Multiple versions of full segment at start_time {}: {}".format(
					start_time, ", ".join(map(str, segments))
				))
				# We've observed some cases where the same segment (with the same hash) will be reported
				# with different durations (generally at stream end). Prefer the longer duration,
				# as this will ensure that if hashes are different we get the most data, and if they
				# are the same it should keep holes to a minimum.
				# If same duration, we have to pick one, so pick highest-sorting hash just so we're consistent.
				full_segments = [max(full_segments, key=lambda segment: (segment.duration, segment.hash))]
			yield full_segments[0]
			continue
		# no full segments, fall back to measuring partials.
		yield max(segments, key=lambda segment: os.stat(segment.path).st_size)


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


log_count = prom.Counter("log_count", "Count of messages logged", ["level", "module", "function"])

class PromLogCountsHandler(logging.Handler):
	"""A logging handler that records a count of logs by level, module and function."""
	def emit(self, record):
		log_count.labels(record.levelname, record.module, record.funcName).inc()

	@classmethod
	def install(cls):
		root_logger = logging.getLogger()
		root_logger.addHandler(cls())
