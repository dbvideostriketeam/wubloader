
"""A place for common utilities between wubloader components"""


import base64
import datetime
import errno
import itertools
import json
import logging
import os
import shutil
from collections import namedtuple
from contextlib import contextmanager
from tempfile import TemporaryFile
from uuid import uuid4

import gevent
from gevent import subprocess
from gevent.fileobject import FileObject

from .cached_iterator import CachedIterator
from .stats import timed
from .fixts import FixTS


# These are the set of transition names from the ffmpeg xfade filter that we allow.
# This is mainly here to prevent someone putting in arbitrary strings and causing weird problems.
KNOWN_XFADE_TRANSITIONS = [
	"fade",
	"wipeleft",
	"wiperight",
	"wipeup",
	"wipedown",
	"slideleft",
	"slideright",
	"slideup",
	"slidedown",
	"circlecrop",
	"rectcrop",
	"distance",
	"fadeblack",
	"fadewhite",
	"radial",
	"smoothleft",
	"smoothright",
	"smoothup",
	"smoothdown",
	"circleopen",
	"circleclose",
	"vertopen",
	"vertclose",
	"horzopen",
	"horzclose",
	"dissolve",
	"pixelize",
	"diagtl",
	"diagtr",
	"diagbl",
	"diagbr",
	"hlslice",
	"hrslice",
	"vuslice",
	"vdslice",
	"hblur",
	"fadegrays",
	"wipetl",
	"wipetr",
	"wipebl",
	"wipebr",
	"squeezeh",
	"squeezev",
	"zoomin",
	"fadefast",
	"fadeslow",
	"hlwind",
	"hrwind",
	"vuwind",
	"vdwind",
	"coverleft",
	"coverright",
	"coverup",
	"coverdown",
	"revealleft",
	"revealright",
	"revealup",
	"revealdown",
]

# These are custom transitions implemented using xfade's custom transition support.
# It maps from name to the "expr" value to use.
# In these expressions:
#  X and Y are pixel coordinates
#  A and B are the old and new video's pixel values
#  W and H are screen width and height
#  P is a "progress" number from 0 to 1 that increases over the course of the wipe
CUSTOM_XFADE_TRANSITIONS = {
	# A clock wipe is a 360 degree clockwise sweep around the center of the screen, starting at the top.
	# It is intended to mimic an analog clock and insinuate a passing of time.
	# It is implemented by calculating the angle of the point off a center line (using atan2())
	# then using the new video if progress > that angle (normalized to 0-1).
	"clockwipe": "if(lt((1-atan2(W/2-X,Y-H/2)/PI) / 2, P), A, B)",
	# The classic star wipe is an expanding 5-pointed star from the center.
	# It's mostly a meme.
	# It is implemented by converting to polar coordinates (distance and angle off center),
	# then comparing distance to a star formula derived from here: https://math.stackexchange.com/questions/4293250/how-to-write-a-polar-equation-for-a-five-pointed-star
	# Made by SenseAmidstMadness.
	"starwipe": "if(lt(sqrt(pow(X-W/2,2)+pow(Y-H/2,2))/sqrt(pow(W/2,2)+pow(H/2,2)),pow((1-P),2)*(0.75)*1/cos((2*asin(cos(5*(atan2(Y-H/2,X-W/2)+PI/2)))+PI*3)/(10))), B, A)",
}


def unpadded_b64_decode(s):
	"""Decode base64-encoded string that has had its padding removed.
	Note it takes a unicode and returns a bytes."""
	# right-pad with '=' to multiple of 4
	s = s + '=' * (- len(s) % 4)
	return base64.b64decode(s.encode(), b"-_")


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
		"""Note that suspect is considered partial"""
		return self.type != "full"


def parse_segment_timestamp(hour_str, min_str):
	"""This is faster than strptime, which dominates our segment processing time.
	It takes strictly formatted hour = "%Y-%m-%dT%H" and time = "%M:%S.%f"."""
	year = int(hour_str[0:4])
	month = int(hour_str[5:7])
	day = int(hour_str[8:10])
	hour = int(hour_str[11:13])
	min = int(min_str[0:2])
	sec = int(min_str[3:5])
	microsec_str = min_str[6:]
	microsec_str += '0' * (6 - len(microsec_str)) # right-pad zeros to 6 digits, eg. "123" -> "123000"
	microsec = int(microsec_str)
	return datetime.datetime(year, month, day, hour, min, sec, microsec)


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
		if type not in ('full', 'suspect', 'partial', 'temp'):
			raise ValueError("Unknown type {!r}".format(type))
		hash = None if type == 'temp' else unpadded_b64_decode(hash)
		start = None if hour is None else parse_segment_timestamp(hour, time)
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
		raise ValueError("Bad path {!r}: {}".format(path, e)).with_traceback(e.__traceback__)


class ContainsHoles(Exception):
	"""Raised by get_best_segments() when a hole is found and allow_holes is False"""


def get_best_segments_for_frame(hour_path, timestamp):
	# Add some leeway before and after so that we don't have errors related to
	# landing on a segment edge.
	leeway = datetime.timedelta(seconds=1)
	return get_best_segments(hour_path, timestamp - leeway, timestamp + leeway)


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

	# ...however in the wild we sometimes see timestamps or durations that differ by a few ms.
	# So we allow some fudge factors.
	ALLOWABLE_OVERLAP = 0.01 # 10ms
	ALLOWABLE_GAP = 0.01 # 10ms

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
				gap = (segment.start - prev_end).total_seconds()
				if gap < -ALLOWABLE_OVERLAP:
					# Overlap! This shouldn't happen, though it might be possible due to weirdness
					# if the stream drops then starts again quickly. We simply ignore the overlapping
					# segment and let the algorithm continue.
					logging.info("Overlapping segments: {} overlaps end of {}".format(segment, result[-1]))
					continue
				if result[-1].is_partial or gap > ALLOWABLE_GAP:
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


def list_segment_files(hour_path, include_tombstones=False, include_chat=False):
	"""Return a list of filenames of segments in the given hour path.
	Segment names are not parsed or verified, but only non-hidden .ts files
	without an associated tombstone file will be listed.
	If include_tombstones = true, the tombstone files themselves will also be listed.
	If include_chat = true, .json files will also be listed.
	"""
	try:
		names = os.listdir(hour_path)
	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		# path does not exist, treat it as having no files
		return []

	# Split into name and extension, this makes the later processing easier.
	# Note that ext will include the leading dot, ie. "foo.bar" -> ("foo", ".bar").
	# Files with no extension produce empty string, ie. "foo" -> ("foo", "")
	# and files with leading dots treat them as part of the name, ie. ".foo" -> (".foo", "").
	splits = [os.path.splitext(name) for name in names]

	# Look for any tombstone files, which indicate we should treat the segment file of the same
	# name as though it doesn't exist.
	tombstones = [name for name, ext in splits if ext == '.tombstone']

	# Return non-hidden ts files, except those that match a tombstone.
	segments = [
		name + ext for name, ext in splits
		if name not in tombstones
			and (ext == ".ts" or (include_chat and ext == ".json"))
			and not name.startswith('.')
	]

	if include_tombstones:
		return segments + ["{}.tombstone".format(name) for name in tombstones]
	else:
		return segments


# Maps hour path to (directory contents, cached result).
# If the directory contents are identical, then we can use the cached result for that hour
# instead of re-calculating. If they have changed, we throw out the cached result.
# Since best_segments_by_start returns an iterator that may not be entirely consumed,
# our cached result stores both all results returned so far, and the live iterator
# in case we need to continue consuming.
_best_segments_by_start_cache = {}

def best_segments_by_start(hour):
	"""Within a given hour path, yield the "best" segment per unique segment start time.
	Best is defined as type=full, or failing that type=suspect, or failing that the longest type=partial.
	Note this means this function may perform os.stat()s.
	"""
	segment_paths = list_segment_files(hour)
	segment_paths.sort()

	# if result is in the cache and the segment_paths haven't changed, return cached result
	if hour in _best_segments_by_start_cache:
		prev_segment_paths, cached_result = _best_segments_by_start_cache[hour]
		if prev_segment_paths == segment_paths:
			return cached_result

	# otherwise create new result and cache it
	result = CachedIterator(_best_segments_by_start(hour, segment_paths))
	_best_segments_by_start_cache[hour] = segment_paths, result
	return result


def _best_segments_by_start(hour, segment_paths):
	# raise a warning for any files that don't parse as segments and ignore them
	parsed = []
	for name in segment_paths:
		try:
			parsed.append(parse_segment_path(os.path.join(hour, name)))
		except ValueError:
			logging.warning("Failed to parse segment {!r}".format(os.path.join(hour, name)), exc_info=True)

	for start_time, segments in itertools.groupby(parsed, key=lambda segment: segment.start):
		# ignore temp segments as they might go away by the time we want to use them
		segments = [segment for segment in segments if segment.type != "temp"]
		if not segments:
			# all segments were temp, move on
			continue

		full_segments = [segment for segment in segments if not segment.is_partial]
		if full_segments:
			if len(full_segments) != 1:
				logging.info("Multiple versions of full segment at start_time {}: {}".format(
					start_time, ", ".join(map(str, segments))
				))
				# We've observed some cases where the same segment (with the same hash) will be reported
				# with different durations (generally at stream end). Prefer the longer duration (followed by longest size),
				# as this will ensure that if hashes are different we get the most data, and if they
				# are the same it should keep holes to a minimum.
				# If same duration and size, we have to pick one, so pick highest-sorting hash just so we're consistent.
				sizes = {segment: os.stat(segment.path).st_size for segment in segments}
				full_segments = [max(full_segments, key=lambda segment: (segment.duration, sizes[segment], segment.hash))]
			yield full_segments[0]
			continue
		# no full segments, fall back to measuring partials. Prefer suspect over partial.
		yield max(segments, key=lambda segment: (
			1 if segment.type == 'suspect' else 0,
			os.stat(segment.path).st_size,
		))


def streams_info(segment):
	"""Return ffprobe's info on streams as a list of dicts"""
	output = subprocess.check_output([
		'ffprobe',
		'-hide_banner', '-loglevel', 'fatal', # suppress noisy output
		'-of', 'json', '-show_streams', # get streams info as json
		segment.path,
	])
	# output here is a bytes, but json.loads will accept it
	return json.loads(output)['streams']


def ffmpeg_cut_segment(segment, cut_start=None, cut_end=None):
	"""
	Wrapper for ffmpeg_cut_many() which cuts a single segment file to stdout,
	taking care to preserve stream order and other metadata.
	Used when doing a fast cut.
	"""
	logging.debug(f"Will cut segment for range ({cut_start}, {cut_end}): {segment.path}")

	args = []
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
	# disable B-frames (frames which contain data needed by earlier frames) as a codec option,
	# as it changes the order that frames go in the file, which messes with our "concatenate the
	# packets" method of concatenating the video.
	args += ['-bf', '0']
	# output as MPEG-TS
	args += ['-f', 'mpegts']

	return ffmpeg_cut_one([segment], args)


def ffmpeg_cut_one(segments, encode_args, output_file=subprocess.PIPE, input_args=[]):
	"""Wrapper for ffmpeg_cut_many() with a simpler API for the single-input case."""
	return ffmpeg_cut_many([(segments, input_args)], encode_args, output_file=output_file)


@contextmanager
def ffmpeg_cut_many(inputs, encode_args, output_file=subprocess.PIPE):
	"""
	Context manager that produces a Popen object which is ffmpeg cutting the given inputs.

	INPUTS is a list of (segments, input_args). The list of segments will be fed as input data,
	preceeded by the given input args.
	OUTPUT_FILE may be a writable file object (with fileno) or subprocess.PIPE.
	If subprocess.PIPE, then output can be read from the Popen object's stdout.
	Using a stdout pipe is preferred but a file can be useful if the output needs to be seekable.

	Upon successful context exit, we block until ffmpeg finishes and raise if anything errored.
	Upon unsuccessful exit, ffmpeg will be killed if still running.
	In either case all files will be closed and everything cleaned up.
	"""
	BASE_ARGS = [
		'ffmpeg',
		'-hide_banner', '-loglevel', 'error', # suppress noisy output
	]

	if output_file is subprocess.PIPE:
		output_args = ['-'] # output to stdout
	else:
		output_args = [
			# We want ffmpeg to write to our tempfile, which is its stdout.
			# However, it assumes that '-' means the output is not seekable.
			# We trick it into understanding that its stdout is seekable by
			# telling it to write to the fd via its /proc/self filename.
			'/proc/self/fd/1',
			# But of course, that file "already exists", so we need to give it
			# permission to "overwrite" it.
			'-y',
		]

	input_pipes = []
	input_feeders = []
	ffmpeg = None
	try:

		# Create pipes and feeders, and prepare input args
		all_input_args = []
		for segments, input_args in inputs:
			# prepare the input pipe
			read_fd, write_fd = os.pipe()
			input_pipes.append(read_fd)
			# set up the writer to fill the pipe
			write_file = FileObject(write_fd, 'wb')
			input_feeder = gevent.spawn(feed_input, segments, write_file)
			input_feeders.append(input_feeder)
			# add input file to ffmpeg args
			all_input_args += input_args + ["-i", "/proc/self/fd/{}".format(read_fd)]

		# Prepare final arg list and spawn the process
		args = BASE_ARGS + all_input_args + encode_args + output_args
		args = list(map(str, args))
		logging.info("Running ffmpeg with args: {}".format(" ".join(args)))
		ffmpeg = subprocess.Popen(args, stdout=output_file, pass_fds=input_pipes)

		# Close input fds now that the child is holding them.
		# Note we remove them from the list one at a time so any failure in a close()
		# call will still close the rest of them during cleanup.
		while input_pipes:
			fd = input_pipes.pop()
			os.close(fd)

		# produce context manager result, everything after this only applies if
		# the context block succeeds
		yield ffmpeg

		# check if any errors occurred in input writing, or if ffmpeg exited non-success.
		if ffmpeg.wait() != 0:
			raise Exception("Error while cutting: ffmpeg exited {}".format(ffmpeg.returncode))
		for input_feeder in input_feeders:
			input_feeder.get() # re-raise any errors from feed_input() calls

	finally:
		# if something goes wrong, try to clean up ignoring errors
		for input_feeder in input_feeders:
			input_feeder.kill()
		if ffmpeg is not None and ffmpeg.poll() is None:
			for action in (ffmpeg.kill, ffmpeg.stdin.close, ffmpeg.stdout.close):
				try:
					action()
				except (OSError, IOError):
					pass
		for fd in input_pipes:
			try:
				os.close(fd)
			except (OSError, IOError):
				pass


def read_chunks(fileobj, chunk_size=16*1024):
	"""Read fileobj until EOF, yielding chunk_size sized chunks of data."""
	while True:
		chunk = fileobj.read(chunk_size)
		if not chunk:
			break
		yield chunk


def range_total(ranges):
	return sum([
		end - start for start, end in ranges
	], datetime.timedelta()).total_seconds()


@timed('cut', cut_type='rough', normalize=lambda ret, sr, ranges: range_total(ranges))
def rough_cut_segments(segment_ranges, ranges):
	"""Yields chunks of a MPEGTS video file covering at least the timestamp ranges,
	likely with a few extra seconds on either side of each range. Ranges are cut between
	with no transitions.
	This method works by simply concatenating all the segments, without any re-encoding.
	"""
	for segments in segment_ranges:
		yield from read_segments(segments)


@timed('cut', cut_type='fast', normalize=lambda ret, sr, ranges: range_total(ranges))
def fast_cut_segments(segment_ranges, ranges, transitions, smart=False):
	"""Yields chunks of a MPEGTS video file covering the exact timestamp ranges.
	segments should be a list of segment lists as returned by get_best_segments() for each range.
	This method works by only cutting the first and last segments of each range
	(or more if there are longer transitions), and concatenating everything together.
	This only works if the same codec settings etc are used across all segments.
	This should almost always be true but may cause weird results if not.
	"""
	if not (len(segment_ranges) == len(ranges) == len(transitions) + 1):
		raise ValueError("Cut input length mismatch: {} segment ranges, {} time ranges, {} transitions".format(
			len(segment_ranges),
			len(ranges),
			len(transitions),
		))

	# We subdivide each range into a start, middle and end.
	# The start covers any incoming transition + a partial first segment.
	# The end covers any outgoing transition + a partial last segment.
	# The middle is everything else, split on any discontinuities.
	# Furthermore, one range's start may be cut together with the previous range's end
	# if there is a transition.
	# We collect iterators covering all of these sections into a single ordered list.
	parts = []
	# In each iteration we handle:
	# - The transition, including previous range's end + this range's start, if there is one
	# - Otherwise, we handle this range's start but assume previous range's end is already done
	# - This range's middle
	# - This range's end, unless it's part of the next transition.
	# We pass the previous range's end segments and offset to the next iteration via prev_end
	prev_end = None # None | (segments, offset)
	for segments, (start, end), in_transition, out_transition in zip(
		segment_ranges,
		ranges,
		# pad transitions with an implicit "hard cut" before and after the actual ranges.
		[None] + transitions,
		transitions + [None],
	):
		# prev_end should be set if and only if there is an in transition
		assert (in_transition is None) == (prev_end is None)

		# Determine start and end cut points, unless we start/end with a discontinuity
		cut_start = None
		cut_end = None
		if segments[0] is not None:
			cut_start = (start - segments[0].start).total_seconds()
			if cut_start < 0: 
				raise ValueError("First segment doesn't begin until after cut start, but no leading hole indicated")
		if segments[-1] is not None:
			cut_end = (end - segments[-1].start).total_seconds()
			if cut_end < 0:
				raise ValueError("Last segment ends before cut end, but no trailing hole indicated")

		# Handle start
		start_cut_end = None
		if in_transition is not None:
			video_type, duration = in_transition
			# Get start segments, and split them from the full range of segments
			# by finding the first segment that starts after the transition ends
			transition_end = start + datetime.timedelta(seconds=duration)
			for i, segment in enumerate(segments):
				if segment is not None and segment.start > transition_end:
					start_segments = segments[:i]
					segments = segments[i:]
					break
			else:
				# Unlikely,but in this case the start transition is the entire range
				# and we should include the end cut.
				start_segments = segments
				segments = []
				start_cut_end = cut_end
				cut_end = None
			if len(start_segments) == 0:
				raise ValueError(f"Could not find any video data for {duration}s transition into range ({start}, {end})")
			raise NotImplementedError("no transitions yet")
			# TODO append ffmpeg with transition, start_segments, prev_end, cut_start, start_cut_end
		elif cut_start is not None and cut_start > 0:
			# Cut start segment, unless it is a discontinuity or doesn't need cutting
			segment = segments[0]
			segments = segments[1:]
			if not segments:
				# The whole thing is only one segment, so also apply end cut
				start_cut_end = cut_end
				cut_end = None
			ffmpeg = ffmpeg_cut_segment(segment, cut_start, start_cut_end)
			parts.append(read_from_stdout(ffmpeg))
		else:
			pass # No cutting required at start

		prev_end = None

		# Handle end, but don't append it to parts list just yet.
		end_cut_part = None
		if out_transition is not None:
			video_type, duration = out_transition
			# Get end segments, and split them from the full range of segments
			# by finding the last segment that ends before the transition starts
			transition_start = end - datetime.timedelta(seconds=duration)
			for i, segment in enumerate(segments):
				if segment is not None and segment.end >= transition_start:
					end_segments = segments[i:]
					segments = segments[:i]
			else:
				raise ValueError(f"Could not find any video data for {duration}s transition out of range ({start}, {end}) that is not already part of another transition")
			# offset is how many seconds into end_segments the transition should start.
			# We know that end_segments is not empty as otherwise we would have hit the for/else condition.
			# We also know that end_segments[0] is not None as it is one of our conditions for picking it.
			# It is however possible for end_segments[0] to start AFTER the transition should have started
			# due to a hole immediately before. Technically a negative offset is still correct in this case,
			# and ideally would cause ffmpeg to treat the transition as "already in progress" when we start.
			# I haven't tested this behaviour but the alternative is to just fail so it's worth a shot.
			offset = (transition_start - end_segments[0].start).total_seconds()
			prev_end = end_segments, offset
		elif cut_end is not None:
			# Cut end segment, unless it is a discontinuity, doesn't need cutting, or was already
			# cut as part of start (which sets cut_end to None).
			assert segments # Either we should still have segments left, or the start cut should have included the end
			segment = segments[-1]
			segments = segments[:-1]
			ffmpeg = ffmpeg_cut_segment(segment, cut_end=cut_end)
			end_cut_part = read_from_stdout(ffmpeg)

		# For each remaining segment in the middle, append a part per run without a discontinuity
		run = []
		for segment in segments:
			if segment is None:
				if run:
					parts.append(read_segments(run))
				run = []
			else:
				run.append(segment)
		if run:
			parts.append(read_segments(run))

		if end_cut_part is not None:
			parts.append(end_cut_part)

	# after all that, double check the last range had no transition and we carried nothing over
	assert prev_end is None

	# yield from each part in order, applying fixts if needed
	fixts = FixTSSequence() if smart else None
	for part in parts:
		for i, chunk in enumerate(part):
			# Since long smart cuts can be CPU and disk bound for quite a while,
			# yield to give other things a chance to run. Note this will run on the first
			# iteration so every part switch also introduces an idle yield.
			if i % 1000 == 0:
				gevent.idle()
			yield fixts.feed(chunk) if smart else chunk
		if fixts:
			fixts.next()


def read_from_stdout(ffmpeg_context):
	"""Takes a ffmpeg context manager as returned by ffmpeg_cut_many() and its wrapper functions,
	and yields data chunks from ffmpeg's stdout."""
	with ffmpeg_context as ffmpeg:
		yield from read_chunks(ffmpeg.stdout)


def read_segments(segments):
	"""Takes a list of segment files and yields data chunks from each one in order. Ignores holes."""
	for segment in segments:
		if segment is None:
			continue
		with open(segment.path, 'rb') as f:
			yield from read_chunks(f)


class FixTSSequence:
	"""Manages state for concatenating several videos while fixing all their timestamps.
	Has the same api as FixTS except instead of end(), we have next(), which  also
	resets the FixTS to take the next input video."""
	def __init__(self):
		self.fixts = FixTS(0)

	def feed(self, data):
		return self.fixts.feed(data)

	def next(self):
		# Note that if FixTS was unused (no data given) this is a no-op.
		# In fact it's theoretically safe to call this function as often as you want
		# (as long as you're sure you have no partial packets) as the only consequence
		# is that we use a fixed time before the next timestamp instead of the timing from
		# the original segments.
		t = self.fixts.end()
		self.fixts = FixTS(t)


@timed('cut', cut_type='smart', normalize=lambda ret, sr, ranges: range_total(ranges))
def smart_cut_segments(segment_ranges, ranges, transitions):
	"""
	As per fast_cut_segments(), except we also do a "fix" pass over the resulting video stream
	to re-time internal timestamps to avoid discontinuities and make sure the video starts at t=0.
	"""
	return fast_cut_segments(segment_ranges, ranges, transitions, smart=True)


def feed_input(segments, pipe):
	"""Write each segment's data into the given pipe in order.
	This is used to provide input to ffmpeg in a full cut."""
	for segment in segments:
		with open(segment.path, 'rb') as f:
			try:
				shutil.copyfileobj(f, pipe)
			except OSError as e:
				# ignore EPIPE, as this just means the end cut meant we didn't need all it
				if e.errno != errno.EPIPE:
					raise
	pipe.close()


@timed('cut_range',
	cut_type=lambda _, segment_ranges, ranges, encode_args, stream=False: ("full-streamed" if stream else "full-buffered"),
	normalize=lambda _, segment_ranges, ranges, *a, **k: range_total(ranges),
)
def full_cut_segments(segment_ranges, ranges, transitions, encode_args, stream=False):
	"""If stream=true, assume encode_args gives a streamable format,
	and begin returning output immediately instead of waiting for ffmpeg to finish
	and buffering to disk."""

	# validate input lengths match up
	if not (len(segment_ranges) == len(ranges) == len(transitions) + 1):
		raise ValueError("Full cut input length mismatch: {} segment ranges, {} time ranges, {} transitions".format(
			len(segment_ranges),
			len(ranges),
			len(transitions),
		))

	inputs = []
	for segments, (start, end) in zip(segment_ranges, ranges):
		# Remove holes
		segments = [segment for segment in segments if segment is not None]
		# how far into the first segment to begin
		cut_start = max(0, (start - segments[0].start).total_seconds())
		# how long the whole section should be (sets the end cut)
		duration = (end - start).total_seconds()
		args = [
			"-ss", cut_start,
			"-t", duration,
		]
		inputs.append((segments, args))

	filters = []
	# with no additional ranges, the output stream is just the first input stream
	output_video_stream = "0:v"
	output_audio_stream = "0:a"
	for i, (transition, prev_range) in enumerate(zip(transitions, ranges)):
		# combine the current output stream with the next input stream
		prev_video_stream = output_video_stream
		prev_audio_stream = output_audio_stream
		next_video_stream = f"{i+1}:v"
		next_audio_stream = f"{i+1}:a"

		# set new output streams
		output_video_stream = f"v{i}"
		output_audio_stream = f"a{i}"

		# small helper for dealing with filter formatting
		def add_filter(name, inputs, outputs, **kwargs):
			inputs = "".join(f"[{stream}]" for stream in inputs)
			outputs = "".join(f"[{stream}]" for stream in outputs)
			kwargs = ":".join(f"{k}={v}" for k, v in kwargs.items())
			filters.append(f"{inputs}{name}={kwargs}{outputs}")

		if transition is None:
			input_streams = [
				prev_video_stream,
				prev_audio_stream,
				next_video_stream,
				next_audio_stream,
			]
			output_streams = [output_video_stream, output_audio_stream]
			add_filter("concat", input_streams, output_streams, n=2, v=1, a=1)
		else:
			video_type, duration = transition

			# transition should start at DURATION seconds before prev_range ends,
			# which is timed relative to prev_range start. So if prev_range is 60s long
			# and duration is 2s, we should start at 58s.
			prev_length = (prev_range[1] - prev_range[0]).total_seconds()
			offset = prev_length - duration
			kwargs = {
				"duration": duration,
				"offset": offset,
			}
			if video_type in CUSTOM_XFADE_TRANSITIONS:
				kwargs["transition"] = "custom"
				kwargs["expr"] = f"'{CUSTOM_XFADE_TRANSITIONS[video_type]}'" # wrap in '' for quoting
			elif video_type in KNOWN_XFADE_TRANSITIONS:
				kwargs["transition"] = video_type
			else:
				raise ValueError(f"Unknown video transition type: {video_type}")
			add_filter("xfade", [prev_video_stream, next_video_stream], [output_video_stream], **kwargs)

			# audio cross-fade across the same period
			add_filter("acrossfade", [prev_audio_stream, next_audio_stream], [output_audio_stream], duration=duration)

	if stream:
		# When streaming, we can just use a pipe
		output_file = subprocess.PIPE
	else:
		# Some ffmpeg output formats require a seekable file.
		# For the same reason, it's not safe to begin uploading until ffmpeg
		# has finished. We create a temporary file for this.
		output_file = TemporaryFile()

	args = []
	if filters:
		args += [
			"-filter_complex", "; ".join(filters),
			"-map", f"[{output_video_stream}]",
			"-map", f"[{output_audio_stream}]",
		]
	args += encode_args

	with ffmpeg_cut_many(inputs, args, output_file) as ffmpeg:
		# When streaming, we can return data as it is available.
		# Otherwise, just exit the context manager so tempfile is fully written.
		if stream:
			for chunk in read_chunks(ffmpeg.stdout):
				yield chunk

	# When not streaming, we can only return the data once ffmpeg has exited
	if not stream:
		for chunk in read_chunks(output_file):
			yield chunk


@timed('cut', cut_type='archive', normalize=lambda ret, sr, ranges: range_total(ranges))
def archive_cut_segments(segment_ranges, ranges, tempdir):
	"""
	Archive cuts are special in a few ways.
	Like a rough cut, they do not take explicit start/end times but instead
	use the entire segment range.
	Like a full cut, they are passed entirely through ffmpeg.
	They explicitly use ffmpeg arguments to copy the video without re-encoding,
	but are placed into an MKV container.
	They are split at each discontinuity into seperate videos.
	Finally, because the files are expected to be very large and non-streamable,
	instead of streaming the data back to the caller, we return a list of temporary filenames
	which the caller should then do something with (probably either read then delete, or rename).
	"""
	# don't re-encode anything, just put it into an MKV container
	encode_args = ["-c", "copy", "-f", "matroska"]
	# We treat multiple segment ranges as having an explicit discontinuity between them.
	# So we apply split_contiguous() to each range, then flatten.
	contiguous_ranges = []
	for segments in segment_ranges:
		contiguous_ranges += list(split_contiguous(segments))
	for segments in contiguous_ranges:
		tempfile_name = os.path.join(tempdir, "archive-temp-{}.mkv".format(uuid4()))
		try:
			with open(tempfile_name, "wb") as tempfile:
				with ffmpeg_cut_one(segments, encode_args, output_file=tempfile):
					# We just want ffmpeg to run to completion, which ffmpeg_cut_one()
					# will do on exit for us.
					pass
		except:
			# if something goes wrong, try to delete the tempfile
			try:
				os.remove(tempfile_name)
			except (OSError, IOError):
				pass
			raise
		else:
			# Success, inform caller of tempfile. It's now their responsibility to delete.
			yield tempfile_name


@timed('waveform')
def render_segments_waveform(segments, size=(1024, 128), scale='sqrt', color='#000000'):
	"""
	Render an audio waveform of given list of segments. Yields chunks of PNG data.
	Note we do not validate our inputs before passing them into an ffmpeg filtergraph.
	Do not provide untrusted input without verifying, or else they can run arbitrary filters
	(this MAY be fine but I wouldn't be shocked if some obscure filter lets them do arbitrary
	filesystem writes).
	"""
	width, height = size

	# Remove holes
	segments = [segment for segment in segments if segment is not None]

	args = [
		# create waveform from input audio
		'-filter_complex',
		f'[0:a]showwavespic=size={width}x{height}:colors={color}:scale={scale}[out]',
		# use created waveform as our output
		'-map', '[out]',
		# output as png
		'-f', 'image2', '-c', 'png',
	]
	with ffmpeg_cut_one(segments, args) as ffmpeg:
		for chunk in read_chunks(ffmpeg.stdout):
			yield chunk


@timed('extract_frame')
def extract_frame(segments, timestamp):
	"""
	Extract the frame at TIMESTAMP within SEGMENT, yielding it as chunks of PNG data.
	"""

	# Remove holes
	segments = [segment for segment in segments if segment is not None]

	if not segments:
		raise ValueError("No data at timestamp within segment list")

	# "cut" input so that first frame is our target frame
	cut_start = (timestamp - segments[0].start).total_seconds()
	input_args = ["-ss", cut_start]

	args = [
		# get a single frame
		'-vframes', '1',
		# output as png
		'-f', 'image2', '-c', 'png',
	]
	with ffmpeg_cut_one(segments, args, input_args=input_args) as ffmpeg:
		for chunk in read_chunks(ffmpeg.stdout):
			yield chunk


def split_contiguous(segments):
	"""For a list of segments, return a list of contiguous ranges of segments.
	In other words, it splits the list every time there is a hole.
	Each range will contain at least one segment.
	"""
	contiguous = []
	for segment in segments:
		if segment is None:
			if contiguous:
				yield contiguous
			contiguous = []
		else:
			contiguous.append(segment)
	if contiguous:
		yield contiguous
