
"""A place for common utilities between wubloader components"""


import base64
import datetime
import errno
import itertools
import json
import logging
import os
import shutil
import sys
from collections import namedtuple
from contextlib import closing
from tempfile import TemporaryFile

import gevent
from gevent import subprocess

from .stats import timed


def unpadded_b64_decode(s):
	"""Decode base64-encoded string that has had its padding removed"""
	# right-pad with '=' to multiple of 4
	s = s + '=' * (- len(s) % 4)
	return base64.b64decode(s, "-_")


class SegmentInfo(
	namedtuple('SegmentInfoBase', [
		'path', 'channel', 'quality', 'start', 'duration', 'type', 'hash'
	])
):
	"""Info parsed from a segment path, including original path.
	Note that start time is a datetime and duration is a timedelta, and hash is a decoded binary string."""
	@property
	def end(self):
		return self.start + self.duration
	@property
	def is_partial(self):
		return self.type != "full"


def parse_segment_path(path):
	"""Parse segment path, returning a SegmentInfo. If path is only the trailing part,
	eg. just a filename, it will leave unknown fields as None."""
	parts = path.split('/')
	# left-pad parts with None up to 4 parts
	parts = [None] * (4 - len(parts)) + parts
	# pull info out of path parts
	channel, quality, hour, filename = parts[-4:]
	# split filename, which should be TIME-DURATION-TYPE-HASH.ts
	try:
		if not filename.endswith('.ts'):
			raise ValueError("Does not end in .ts")
		filename = filename[:-len('.ts')] # chop off .ts
		parts = filename.split('-', 3)
		if len(parts) != 4:
			raise ValueError("Not enough dashes in filename")
		time, duration, type, hash = parts
		if type not in ('full', 'partial', 'temp'):
			raise ValueError("Unknown type {!r}".format(type))
		hash = None if type == 'temp' else unpadded_b64_decode(hash)
		start = None if hour is None else datetime.datetime.strptime("{}:{}".format(hour, time), "%Y-%m-%dT%H:%M:%S.%f")
		return SegmentInfo(
			path = path,
			channel = channel,
			quality = quality,
			start = start,
			duration = datetime.timedelta(seconds=float(duration)),
			type = type,
			hash = hash,
		)
	except ValueError as e:
		# wrap error but preserve original traceback
		_, _, tb = sys.exc_info()
		raise ValueError, ValueError("Bad path {!r}: {}".format(path, e)), tb


class ContainsHoles(Exception):
	"""Raised by get_best_segments() when a hole is found and allow_holes is False"""


@timed(
	hours_path=lambda ret, hours_path, *args, **kwargs: hours_path,
	has_holes=lambda ret, *args, **kwargs: None in ret,
	normalize=lambda ret, *args, **kwargs: len([x for x in ret if x is not None]),
)
def get_best_segments(hours_path, start, end, allow_holes=True):
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

	If allow_holes is False, then we fail fast at the first discontinuity found
	and raise ContainsHoles. If ContainsHoles is not raised, the output is guarenteed to not contain
	any None items.
	"""
	# Note: The exact equality checks in this function are not vulnerable to floating point error,
	# but only because all input dates and durations are only precise to the millisecond, and
	# python's datetime types represent these as integer microseconds internally. So the parsing
	# to these types is exact, and all operations on them are exact, so all operations are exact.

	result = []

	for hour in hour_paths_for_range(hours_path, start, end):
		# Especially when processing multiple hours, this routine can take a signifigant amount
		# of time with no blocking. To ensure other stuff is still completed in a timely fashion,
		# we yield to let other things run.
		gevent.idle()

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
					if not allow_holes:
						raise ContainsHoles
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
					if not allow_holes:
						raise ContainsHoles
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

	# check if we need a trailing None because last segment is partial or doesn't reach end,
	# or we found nothing at all
	if not result or result[-1].is_partial or result[-1].end < end:
		if not allow_holes:
			raise ContainsHoles
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
	# raise a warning for any files that don't parse as segments and ignore them
	parsed = []
	for name in segment_paths:
		try:
			parsed.append(parse_segment_path(os.path.join(hour, name)))
		except ValueError as e:
			logging.warning("Failed to parse segment {!r}".format(os.path.join(hour, name)), exc_info=True)

	for start_time, segments in itertools.groupby(parsed, key=lambda segment: segment.start):
		# ignore temp segments as they might go away by the time we want to use them
		segments = [segment for segment in segments if segment.type != "temp"]

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


def streams_info(segment):
	"""Return ffprobe's info on streams as a list of dicts"""
	output = subprocess.check_output([
		'ffprobe',
		'-hide_banner', '-loglevel', 'fatal', # suppress noisy output
		'-of', 'json', '-show_streams', # get streams info as json
		segment.path,
	])
	return json.loads(output)['streams']


def ffmpeg_cut_segment(segment, cut_start=None, cut_end=None):
	"""Return a Popen object which is ffmpeg cutting the given single segment.
	This is used when doing a fast cut.
	"""
	args = [
		'ffmpeg',
		'-hide_banner', '-loglevel', 'error', # suppress noisy output
		'-i', segment.path,
	]
	# output from ffprobe is generally already sorted but let's be paranoid,
	# because the order of map args matters.
	for stream in sorted(streams_info(segment), key=lambda stream: stream['index']):
		# map the same stream in the same position from input to output
		args += ['-map', '0:{}'.format(stream['index'])]
		if stream['codec_type'] in ('video', 'audio'):
			# for non-metadata streams, make sure we use the same codec (metadata streams
			# are a bit weirder, and ffmpeg will do the right thing anyway)
			args += ['-codec:{}'.format(stream['index']), stream['codec_name']]
	# now add trim args
	if cut_start:
		args += ['-ss', str(cut_start)]
	if cut_end:
		args += ['-to', str(cut_end)]
	# output to stdout as MPEG-TS
	args += ['-f', 'mpegts', '-']
	# run it
	logging.info("Running segment cut with args: {}".format(" ".join(args)))
	return subprocess.Popen(args, stdout=subprocess.PIPE)


def ffmpeg_cut_stdin(output_file, cut_start, duration, encode_args):
	"""Return a Popen object which is ffmpeg cutting from stdin.
	This is used when doing a full cut.
	If output_file is not subprocess.PIPE,
	uses explicit output file object instead of using a pipe,
	because some video formats require a seekable file.
	"""
	args = [
		'ffmpeg',
		'-hide_banner', '-loglevel', 'error', # suppress noisy output
		'-i', '-',
		'-ss', cut_start,
		'-t', duration,
	] + list(encode_args)
	if output_file is subprocess.PIPE:
		args.append('-') # output to stdout
	else:
		args += [
			# We want ffmpeg to write to our tempfile, which is its stdout.
			# However, it assumes that '-' means the output is not seekable.
			# We trick it into understanding that its stdout is seekable by
			# telling it to write to the fd via its /proc/self filename.
			'/proc/self/fd/1',
			# But of course, that file "already exists", so we need to give it
			# permission to "overwrite" it.
			'-y',
		]
	args = map(str, args)
	logging.info("Running full cut with args: {}".format(" ".join(args)))
	return subprocess.Popen(args, stdin=subprocess.PIPE, stdout=output_file)


def read_chunks(fileobj, chunk_size=16*1024):
	"""Read fileobj until EOF, yielding chunk_size sized chunks of data."""
	while True:
		chunk = fileobj.read(chunk_size)
		if not chunk:
			break
		yield chunk


@timed('cut', type='fast', normalize=lambda _, segments, start, end: (end - start).total_seconds())
def fast_cut_segments(segments, start, end):
	"""Yields chunks of a MPEGTS video file covering the exact timestamp range.
	segments should be a list of segments as returned by get_best_segments().
	This method works by only cutting the first and last segments, and concatenating the rest.
	This only works if the same codec settings etc are used across all segments.
	This should almost always be true but may cause weird results if not.
	"""

	# how far into the first segment to begin (if no hole at start)
	cut_start = None
	if segments[0] is not None:
		cut_start = (start - segments[0].start).total_seconds()
		if cut_start < 0:
			raise ValueError("First segment doesn't begin until after cut start, but no leading hole indicated")

	# how far into the final segment to end (if no hole at end)
	cut_end = None
	if segments[-1] is not None:
		cut_end = (end - segments[-1].start).total_seconds()
		if cut_end < 0:
			raise ValueError("Last segment ends before cut end, but no trailing hole indicated")

	# Set first and last only if they actually need cutting.
	# Note this handles both the cut_start = None (no first segment to cut)
	# and cut_start = 0 (first segment already starts on time) cases.
	first = segments[0] if cut_start else None
	last = segments[-1] if cut_end else None

	for segment in segments:
		if segment is None:
			logging.debug("Skipping discontinuity while cutting")
			# TODO: If we want to be safe against the possibility of codecs changing,
			# we should check the streams_info() after each discontinuity.
			continue

		# note first and last might be the same segment.
		# note a segment will only match if cutting actually needs to be done
		# (ie. cut_start or cut_end is not 0)
		if segment in (first, last):
			proc = None
			try:
				proc = ffmpeg_cut_segment(
					segment,
					cut_start if segment == first else None,
					cut_end if segment == last else None,
				)
				with closing(proc.stdout):
					for chunk in read_chunks(proc.stdout):
						yield chunk
				proc.wait()
			except Exception:
				ex, ex_type, tb = sys.exc_info()
				# try to clean up proc, ignoring errors
				if proc is not None:
					try:
						proc.kill()
					except OSError:
						pass
				raise ex, ex_type, tb
			else:
				# check if ffmpeg had errors
				if proc.returncode != 0:
					raise Exception(
						"Error while streaming cut: ffmpeg exited {}".format(proc.returncode)
					)
		else:
			# no cutting needed, just serve the file
			with open(segment.path) as f:
				for chunk in read_chunks(f):
					yield chunk


def feed_input(segments, pipe):
	"""Write each segment's data into the given pipe in order.
	This is used to provide input to ffmpeg in a full cut."""
	for segment in segments:
		with open(segment.path) as f:
			try:
				shutil.copyfileobj(f, pipe)
			except OSError as e:
				# ignore EPIPE, as this just means the end cut meant we didn't need all i>
				if e.errno != errno.EPIPE:
					raise
	pipe.close()


@timed('cut',
	type=lambda _, segments, start, end, encode_args, stream=False: "full-streamed" if stream else "full-buffered",
	normalize=lambda _, segments, start, end, *a, **k: (end - start).total_seconds()),
)
def full_cut_segments(segments, start, end, encode_args, stream=False):
	"""If stream=true, assume encode_args gives a streamable format,
	and begin returning output immediately instead of waiting for ffmpeg to finish
	and buffering to disk."""
	# how far into the first segment to begin
	cut_start = max(0, (start - segments[0].start).total_seconds())
	# duration
	duration = (end - start).total_seconds()

	ffmpeg = None
	input_feeder = None
	try:

		if stream:
			# When streaming, we can just use a pipe
			tempfile = subprocess.PIPE
		else:
			# Some ffmpeg output formats require a seekable file.
			# For the same reason, it's not safe to begin uploading until ffmpeg
			# has finished. We create a temporary file for this.
			tempfile = TemporaryFile()

		ffmpeg = ffmpeg_cut_stdin(tempfile, cut_start, duration, encode_args)
		input_feeder = gevent.spawn(feed_input, segments, ffmpeg.stdin)

		# When streaming, we can return data as it is available
		if stream:
			for chunk in read_chunks(ffmpeg.stdout):
				yield chunk

		# check if any errors occurred in input writing, or if ffmpeg exited non-success.
		if ffmpeg.wait() != 0:
			raise Exception("Error while streaming cut: ffmpeg exited {}".format(ffmpeg.returncode))
		input_feeder.get() # re-raise any errors from feed_input()

		# When not streaming, we can only return the data once ffmpeg has exited
		if not stream:
			for chunk in read_chunks(tempfile):
				yield chunk
	finally:
		# if something goes wrong, try to clean up ignoring errors
		if input_feeder is not None:
			input_feeder.kill()
		if ffmpeg is not None and ffmpeg.poll() is None:
			for action in (ffmpeg.kill, ffmpeg.stdin.close, ffmpeg.stdout.close):
				try:
					action()
				except (OSError, IOError):
					pass
