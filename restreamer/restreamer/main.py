
import datetime
import errno
import functools
import json
import logging
import os
import subprocess
from uuid import uuid4

import gevent
import gevent.backdoor
import gevent.event
import prometheus_client as prom
from flask import Flask, url_for, request, abort, Response
from gevent.pywsgi import WSGIServer

from common import database, dateutil, get_best_segments, rough_cut_segments, fast_cut_segments, full_cut_segments, PromLogCountsHandler, install_stacksampler, serve_with_graceful_shutdown
from common.flask_stats import request_stats, after_request
from common.images import compose_thumbnail_template, get_template
from common.segments import smart_cut_segments, feed_input, render_segments_waveform, extract_frame, list_segment_files, get_best_segments_for_frame
from common.chat import get_batch_file_range, merge_messages
from common.cached_iterator import CachedIterator

from . import generate_hls


app = Flask('restreamer', static_url_path='/segments')
app.after_request(after_request)


"""
The restreamer is a simple http api for listing available segments and generating
HLS playlists for them.

The segments themselves are ideally to be served by some external webserver
under "/segments/<channel>/<quality>/<hour>/<filename>" (ie. with BASE_DIR
under "/segments"), though this server will also serve them if requested.
"""


def listdir(path, error=True):
	"""List files in path, excluding hidden files.
	Behaviour when path doesn't exist depends on error arg.
	If error is True, raise 404. Otherwise, return [].
	"""
	try:
		return [name for name in os.listdir(path) if not name.startswith('.')]
	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		if error:
			abort(404)
		return []


def has_path_args(fn):
	"""Decorator to wrap routes which take args which are to be used as parts of a filepath.
	Disallows hidden folders and path traversal.
	"""
	@functools.wraps(fn)
	def _has_path_args(**kwargs):
		for key, value in kwargs.items():
			# Disallowing a leading . prevents both hidden files and path traversal ("..")
			if value.startswith('.'):
				return "Bad {}: May not start with a period".format(key), 403
		return fn(**kwargs)
	return _has_path_args


def cors(app):
	"""WSGI middleware that sets CORS headers"""
	HEADERS = [
		("Access-Control-Allow-Credentials", "false"),
		("Access-Control-Allow-Headers", "*"),
		("Access-Control-Allow-Methods", "GET,POST,HEAD"),
		("Access-Control-Allow-Origin", "*"),
		("Access-Control-Max-Age", "86400"),
	]
	def handle(environ, start_response):
		def _start_response(status, headers, exc_info=None):
			headers += HEADERS
			return start_response(status, headers, exc_info)
		return app(environ, _start_response)
	return handle


@app.route('/metrics')
@request_stats
def metrics():
	"""Return current metrics in prometheus metrics format"""
	return prom.generate_latest()

# To make nginx proxying simpler, we want to allow /metrics/* to work
@app.route('/metrics/<trailing>')
@request_stats
def metrics_with_trailing(trailing):
	"""Expose Prometheus metrics."""
	return prom.generate_latest()

@app.route('/files')
@request_stats
def list_channels():
	"""Returns a JSON list of channels for which there may be segments available.
	Returns empty list if no channels are available.
	"""
	path = app.static_folder
	return json.dumps(listdir(path, error=False))


@app.route('/files/<channel>')
@request_stats
@has_path_args
def list_qualities(channel):
	"""Returns a JSON list of qualities for the given channel for which there
	may be segments available. Returns empty list on non-existent channels, etc."""
	path = os.path.join(
		app.static_folder,
		channel,
	)
	return json.dumps(listdir(path, error=False))

@app.route('/files/<channel>/<quality>')
@request_stats
@has_path_args
def list_hours(channel, quality):
	"""Returns a JSON list of hours for the given channel and quality for which
	there may be segments available. Returns empty list on non-existent
	channels, etc.
	"""
	path = os.path.join(
		app.static_folder,
		channel,
		quality,
	)
	return json.dumps(listdir(path, error=False))


@app.route('/files/<channel>/<quality>/<hour>')
@request_stats
@has_path_args
def list_segments(channel, quality, hour):
	"""Returns a JSON list of segment or chat files for a given channel, quality and
	hour. Returns empty list on non-existant channels, etc.
	If tombstones = "true", will also list tombstone files for that hour.
	"""
	path = os.path.join(
		app.static_folder,
		channel,
		quality,
		hour,
	)
	tombstones = request.args.get('tombstones', 'false').lower()
	if tombstones not in ["true", "false"]:
		return "tombstones must be one of: true, false", 400
	tombstones = (tombstones == "true")
	return json.dumps(list_segment_files(path, include_tombstones=tombstones, include_chat=True))


@app.route('/extras/<dir>')
@request_stats
@has_path_args
def list_extras(dir):
	"""List all files under directory recursively. All paths returned are relative to dir.
	Files can be fetched under /segments/<dir>/<path>.
	Note this is only intended for extra files, and not for segments.
	"""
	root = os.path.join(app.static_folder, dir)
	result = []
	for path, subdirs, files in os.walk(root):
		relpath = os.path.relpath(path, root)
		for file in files:
			result.append(os.path.normpath(os.path.join(relpath, file)))
	return json.dumps(result)


def time_range_for_quality(channel, quality):
	"""Returns earliest and latest times that the given quality has segments for
	(up to hour resolution), or 404 if it doesn't exist / is empty."""
	hours = listdir(os.path.join(app.static_folder, channel, quality))
	if not hours:
		abort(404)
	first, last = min(hours), max(hours)
	# note last hour parses to _start_ of that hour, so we add 1h to go to end of that hour
	def parse_hour(s):
		return datetime.datetime.strptime(s, "%Y-%m-%dT%H")
	return parse_hour(first), parse_hour(last) + datetime.timedelta(hours=1)


@app.route('/playlist/<channel>.m3u8')
@request_stats
@has_path_args
def generate_master_playlist(channel):
	"""Returns a HLS master playlist for the given channel.
	Takes optional params:
		start, end: The time to begin and end the stream at.
			See generate_media_playlist for details.
	"""
	start = dateutil.parse_utc_only(request.args['start']) if 'start' in request.args else None
	end = dateutil.parse_utc_only(request.args['end']) if 'end' in request.args else None
	qualities = listdir(os.path.join(app.static_folder, channel))

	playlists = {}
	for quality in qualities:
		# "chat" is text only, not an actual video quality
		if quality == "chat":
			continue
		# If start or end are given, try to restrict offered qualities to ones which exist for that
		# time range.
		if start is not None or end is not None:
			first, last = time_range_for_quality(channel, quality)
			if start is not None and last < start:
				continue # last time for quality is before our start time, don't offer quality
			if end is not None and end < first:
				continue # our end time is before first time for quality, don't offer quality
		playlists[quality] = url_for(
			'generate_media_playlist', channel=channel, quality=quality, **request.args
		)

	return generate_hls.generate_master(playlists)


# Generating large media playlists is expensive, especially on the first run
# where the cache is cold. And the video player will make repeated requests.
# To avoid requests piling up and repeating work, if we get the exact same request again
# while the old request is in progress, we piggyback on the previous request and return
# the same result.
# This cache object maps (hour_path, start, end) to an AsyncResult.
_media_playlist_cache = {}

@app.route('/playlist/<channel>/<quality>.m3u8')
@request_stats
@has_path_args
def generate_media_playlist(channel, quality):
	"""Returns a HLS media playlist for the given channel and quality.
	Takes optional params:
		start, end: The time to begin and end the stream at.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
			If not given, effectively means "infinity", ie. no start means
			any time ago, no end means any time in the future.
			However if either are missing and this would cause us to return over 12 hours
			of content, we fail instead.
	Note that because it returns segments _covering_ that range, the playlist
	may start slightly before and end slightly after the given times.
	"""

	hours_path = os.path.join(app.static_folder, channel, quality)
	if not os.path.isdir(hours_path):
		abort(404)

	start = dateutil.parse_utc_only(request.args['start']) if 'start' in request.args else None
	end = dateutil.parse_utc_only(request.args['end']) if 'end' in request.args else None
	if start is None or end is None:
		# If start or end are not given, use the earliest/latest time available.
		# For end in particular, always pad an extra hour to force a discontinuity at the end
		# even if we happen to have a complete hour available. Otherwise when live streaming you
		# can get an unexpected "video is complete" even though more segments are about to arrive.
		first, last = time_range_for_quality(channel, quality)
		if start is None:
			start = first
		if end is None:
			end = last + datetime.timedelta(hours=1)

	# We still allow > 12hr ranges, but only if done explicitly (both start and end are set).
	if end - start > datetime.timedelta(hours=12) and ('start' not in request.args or 'end' not in request.args):
		return "Implicit range may not be longer than 12 hours", 400

	def _generate_media_playlist():
		cache_key = (hours_path, start, end)

		if cache_key in _media_playlist_cache:
			yield from _media_playlist_cache[cache_key].get()
			return

		result = gevent.event.AsyncResult()
		try:
			# Note we don't populate the cache until we're in the try block,
			# so there is no point where an exception won't be transferred to the result.
			_media_playlist_cache[cache_key] = result

			# get_best_segments requires start be before end, special case that as no segments
			# (not an error because someone might ask for a specific start, no end, but we ended up with
			# end before start because that's the latest time we have)
			if start < end:
				segments = get_best_segments(hours_path, start, end)
			else:
				# Note the None to indicate there was a "hole" at both start and end
				segments = [None]
			iterator = CachedIterator(generate_hls.generate_media(segments, os.path.join(app.static_url_path, channel, quality)))

			# We set the result immediately so that everyone can start returning it.
			# Multiple readers from the CachedIterator is safe.
			result.set(iterator)
		except BaseException as ex:
			result.set_exception(ex)
			raise

		# send the whole response
		yield from iterator

		# Now we're done, remove the async result so a fresh request can start.
		assert _media_playlist_cache.pop(cache_key) is result, "Got someone else's AsyncResult"

	return _generate_media_playlist()


@app.route('/cut/<channel>/<quality>.ts')
@request_stats
@has_path_args
def cut(channel, quality):
	"""Return a MPEGTS video file covering the exact timestamp range.
	Params:
		start, end: The start and end times, down to the millisecond.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
			If not given (and ranges not given), will use the earliest/latest data available.
		range: A pair "START,END" which are formatted as per start and end args.
			Overrides "start" and "end" options.
			This option may be given multiple times.
			The final video will consist of all the ranges cut back to back,
			in the order given, with hard cuts between each range.
		transition: A pair "TYPE,DURATION", or empty string "".
			TYPE is a transition identifier, see common.segments for valid values.
			DURATION is a float number of seconds for the transition to last.
			Empty string indicates a hard cut.
			This option may be given multiple times, with each time applying to the transition
			between the next pair of ranges. It may be given a number of times up to 1 less
			than the number of range args. If given less times than that (or not at all),
			remaining ranges default to a hard cut.
		allow_holes: Optional, default false. If false, errors out with a 406 Not Acceptable
			if any holes are detected, rather than producing a video with missing parts.
			Set to true by passing "true" (case insensitive).
			Even if holes are allowed, a 406 may result if the resulting video (or any individual
			range) would be empty.
		type: One of:
			"rough": A direct concat, like a fast cut but without any ffmpeg.
				It may extend beyond the requested start and end times by a few seconds.
			"fast": Very fast but with minor artifacting where the first and last segments join
				the other segments.
			"smart": Almost as fast as "fast" but without the artifacting.
				Currently experimental, but expected to replace "fast".
			"mpegts": A full cut to a streamable mpegts format. This consumes signifigant server
				resources, so please use sparingly.
	"""
	if 'range' in request.args:
		parts = [part.split(',') for part in request.args.getlist('range')]
		ranges = [
			(dateutil.parse_utc_only(start), dateutil.parse_utc_only(end))
			for start, end in parts
		]
	else:
		start = dateutil.parse_utc_only(request.args['start']) if 'start' in request.args else None
		end = dateutil.parse_utc_only(request.args['end']) if 'end' in request.args else None
		if start is None or end is None:
			# If start or end are not given, use the earliest/latest time available
			first, last = time_range_for_quality(channel, quality)
			if start is None:
				start = first
			if end is None:
				end = last
		ranges = [(start, end)]

	for start, end in ranges:
		if end <= start:
			return "Ends must be after starts", 400

	transitions = []
	for part in request.args.getlist('transition'):
		if part == "":
			transitions.append(None)
		else:
			video_type, duration = part.split(",")
			duration = float(duration)
			transitions.append((video_type, duration))
	if len(transitions) >= len(ranges):
		return "Too many transitions", 400
	# pad with None
	transitions = transitions + [None] * (len(ranges) - 1 - len(transitions))
	has_transitions = any(t is not None for t in transitions)

	allow_holes = request.args.get('allow_holes', 'false').lower()
	if allow_holes not in ["true", "false"]:
		return "allow_holes must be one of: true, false", 400
	allow_holes = (allow_holes == "true")

	hours_path = os.path.join(app.static_folder, channel, quality)
	if not os.path.isdir(hours_path):
		abort(404)

	segment_ranges = []
	for start, end in ranges:
		segments = get_best_segments(hours_path, start, end)
		if not allow_holes and None in segments:
			return "Requested time range contains holes or is incomplete.", 406
		if not any(segment is not None for segment in segments):
			return "We have no content available within the requested time range.", 406
		segment_ranges.append(segments)

	type = request.args.get('type', 'fast')
	if type == 'rough':
		# NOTE: We intentionally ignore transitions for rough cuts, as these are mostly used
		# when downloading source footage for later editing.
		return Response(rough_cut_segments(segment_ranges, ranges), mimetype='video/MP2T')
	elif type == 'fast':
		return Response(fast_cut_segments(segment_ranges, ranges, transitions), mimetype='video/MP2T')
	elif type == 'smart':
		return Response(smart_cut_segments(segment_ranges, ranges, transitions), mimetype='video/MP2T')
	elif type in ('mpegts', 'mp4'):
		if type == 'mp4':
			return "mp4 type has been disabled due to the load it causes", 400
		# encode as high-quality, without wasting too much cpu on encoding
		stream, muxer, mimetype = (True, 'mpegts', 'video/MP2T') if type == 'mpegts' else (False, 'mp4', 'video/mp4')
		encoding_args = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-f', muxer]
		return Response(full_cut_segments(segment_ranges, ranges, transitions, encoding_args, stream=stream), mimetype=mimetype)
	else:
		return "Unknown type {!r}".format(type), 400


@app.route('/waveform/<channel>/<quality>.png')
@request_stats
@has_path_args
def generate_waveform(channel, quality):
	"""
	Returns a PNG image showing the audio waveform over the requested time period.
	Params:
		start, end: Required. The start and end times.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
			The returned image may extend beyond the requested start and end times by a few seconds.
		size: The image size to render in form WIDTHxHEIGHT. Default 1024x64.
	"""
	start = dateutil.parse_utc_only(request.args['start'])
	end = dateutil.parse_utc_only(request.args['end'])
	if end <= start:
		return "End must be after start", 400

	if end - start > datetime.timedelta(hours=6):
		return "Range may not be longer than 6 hours", 400

	size = request.args.get('size', '1024x64')
	try:
		width, height = map(int, size.split('x'))
	except ValueError:
		return "Invalid size", 400
	if not ((0 < width <= 4096) and (0 < height <= 4096)):
		return "Image size must be between 1x1 and 4096x4096", 400

	hours_path = os.path.join(app.static_folder, channel, quality)
	if not os.path.isdir(hours_path):
		abort(404)

	segments = get_best_segments(hours_path, start, end)
	if not any(segment is not None for segment in segments):
		return "We have no content available within the requested time range.", 406

	return Response(render_segments_waveform(segments, (width, height)), mimetype='image/png')


@app.route('/frame/<channel>/<quality>.png')
@request_stats
@has_path_args
def get_frame(channel, quality):
	"""
	Returns a PNG image for the frame at the specific timestamp given.
	Params:
		timestamp: Required. The timestamp to get.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
	"""
	timestamp = dateutil.parse_utc_only(request.args['timestamp'])

	hours_path = os.path.join(app.static_folder, channel, quality)
	if not os.path.isdir(hours_path):
		abort(404)

	segments = get_best_segments_for_frame(hours_path, timestamp)
	if not any(segment is not None for segment in segments):
		return "We have no content available within the requested time range.", 406

	return Response(extract_frame(segments, timestamp), mimetype='image/png')


@app.route('/thumbnail/<channel>/<quality>.png')
@request_stats
@has_path_args
def get_thumbnail_named_template(channel, quality):
	"""
	Returns a PNG image which is a preview of how a thumbnail will be generated.
	Params:
		timestamp: Required. The frame to use as the thumbnail image.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
		template: Required. The template name to use.
			Must be one of the template names as returned by GET /thrimshim/templates
		crop: Left, upper, right, and lower pixel coordinates to crop the selected frame.
			Should be a comma-seperated list of numbers.
			Default is to use the crop in the database.
		location: Left, top, right, bottom pixel coordinates to position the cropped frame.
			Should be a comma-seperated list of numbers.
			Default is to use the location in the databse.
	"""
	crop = request.args.get('crop', None)
	location = request.args.get('location', None)
	if app.db_manager is None:
		return 'A database connection is required to generate thumbnails', 501
	try:
		template, crop, location = get_template(app.db_manager, request.args['template'], crop, location)
	except ValueError:
		return 'Template {} not found'.format(request.args['template']), 404
	logging.info('Generating thumbnail from the video frame at {} using {} as template'.format(request.args['timestamp'], request.args['template']))
	return get_thumbnail(channel, quality, request.args['timestamp'], template, crop, location)


@app.route('/thumbnail/<channel>/<quality>.png', methods=['POST'])
@request_stats
@has_path_args
def get_thumbnail_uploaded_template(channel, quality):
	"""
	Returns a PNG image which is a preview of how a thumbnail will be generated.
	Params:
		timestamp: Required. The frame to use as the thumbnail image.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
		crop: Required. Left, upper, right, and lower pixel coordinates to crop the selected frame.
			Should be a comma-seperated list of numbers.
		location: Required. Left, top, right, bottom pixel coordinates to position the cropped frame.
			Should be a comma-seperated list of numbers.
	"""	
	template = request.data
	logging.info('Generating thumbnail from the video frame at {} using a custom template'.format(request.args['timestamp']))
	return get_thumbnail(channel, quality, request.args['timestamp'], template, request.args['crop'], request.args['location'])


def get_thumbnail(channel, quality, timestamp, template, crop, location):
	"""
	Generates a PNG thumbnail by combining a frame at timestamp with the template.
	"""

	timestamp = dateutil.parse_utc_only(timestamp)

	crop = [int(n) for n in crop.split(",")]
	location = [int(n) for n in location.split(",")]

	hours_path = os.path.join(app.static_folder, channel, quality)
	if not os.path.isdir(hours_path):
		abort(404)

	segments = get_best_segments_for_frame(hours_path, timestamp)
	if not any(segment is not None for segment in segments):
		return "We have no content available within the requested time range.", 406

	frame = b''.join(extract_frame(segments, timestamp))
	template = compose_thumbnail_template(template, frame, crop, location)

	return Response(template, mimetype='image/png')


@app.route('/<channel>/chat.json')
@request_stats
@has_path_args
def get_chat_messages(channel):
	"""
	Returns a JSON list of chat messages from the given time range.
	The messages are in the same format as used in the chat archiver.
	Messages without an exact known time are included if their possible time range
	intersects with the requested time range. Note this means that messages in range (A, B)
	and range (B, C) may overlap! Thankfully the kinds of messages this can happen for mostly
	don't matter - JOINs and PARTs mainly, but sometimes ROOMSTATEs, NOTICEs and CLEARCHATs.
	Params:
		start, end: Required. The start and end times.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
	"""
	try:
		start = dateutil.parse_utc_only(request.args['start'])
		end = dateutil.parse_utc_only(request.args['end'])
	except ValueError:
		return "Invalid timestamp", 400
	if end <= start:
		return "End must be after start", 400

	if end - start > datetime.timedelta(hours=2):
		return "Cannot request more than 2h of chat", 400

	hours_path = os.path.join(app.static_folder, channel, "chat")

	# This process below may fail if a batch is deleted out from underneath us.
	# If that happens, we need to start again.
	retry = True
	while retry:
		retry = False
		messages = []
		for batch_file in get_batch_file_range(hours_path, start, end):
			try:
				with open(batch_file) as f:
					batch = f.read()
			except OSError as e:
				if e.errno != errno.ENOENT:
					raise
				# If file doesn't exist, retry the outer loop
				retry = True
				break
			batch = [json.loads(line) for line in batch.strip().split("\n")]
			messages = merge_messages(messages, batch)

	start = start.timestamp()
	end = end.timestamp()
	messages = sorted(
		[
			m for m in messages
			# message ends after START, and starts before END
			if start <= m['time'] + m['time_range'] and m['time'] < end
		], key=lambda m: (m['time'], m['time_range'])
	)

	return json.dumps(messages)


@app.route('/generate_videos/<channel>/<quality>', methods=['POST'])
@request_stats
@has_path_args
def generate_videos(channel, quality):
	"""
	Takes a JSON body {name: [start, end]} where start and end are timestamps.
	Creates files CHANNEL_QUALITY_NAME_N.mkv for each contiguous range of segments
	in that hour range (ie. split at holes) and saves them in the segments directory.
	"""
	videos = request.json

	for name, (start, end) in videos.items():
		start = dateutil.parse_utc_only(start)
		end = dateutil.parse_utc_only(end)

		# protect against directory traversal
		if "/" in name:
			return "Name cannot contain /", 400

		if end <= start:
			return "End must be after start", 400

		hours_path = os.path.join(app.static_folder, channel, quality)
		if not os.path.isdir(hours_path):
			abort(404)

		segments = get_best_segments(hours_path, start, end)
		contiguous = []
		n = 0
		logging.info("Generating contiguous videos {!r} for {}/{} from {} to {}".format(
			name, channel, quality, start, end,
		))

		def write_file(segments, n):
			output_name = os.path.join(app.static_folder, '{}_{}_{}_{}.mkv'.format(channel, quality, name, n))
			if os.path.exists(output_name):
				logging.info("Skipping generating hours video - already exists")
				return
			temp_name = os.path.join(app.static_folder, "temp-{}.mkv".format(uuid4()))
			args = [
				'ffmpeg',
				'-hide_banner', '-loglevel', 'error', # suppress noisy output
				'-i', '-',
				'-c', 'copy',
				temp_name,
			]
			logging.info("Generating video with args: {}".format(" ".join(args)))
			proc = None
			try:
				proc = subprocess.Popen(args, stdin=subprocess.PIPE)
				# feed_input will write all the segments and close stdin
				feed_input(segments, proc.stdin)
				# now wait for it to finish and check errors
				if proc.wait() != 0:
					raise Exception("ffmpeg exited {}".format(proc.returncode))
				os.rename(temp_name, output_name)
			finally:
				if os.path.exists(temp_name):
					os.remove(temp_name)

		for segment in segments:
			if segment is not None:
				contiguous.append(segment)
				continue
			if contiguous:
				write_file(contiguous, n)
				n += 1
				contiguous = []
		if contiguous:
			write_file(contiguous, n)

	return ''


def main(host='0.0.0.0', port=8000, base_dir='.', backdoor_port=0, connection_string=''):
	app.static_folder = base_dir
	server = WSGIServer((host, port), cors(app))

	PromLogCountsHandler.install()
	install_stacksampler()

	if connection_string:
		app.db_manager = database.DBManager(dsn=connection_string)
	else:
		app.db_manager = None

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	serve_with_graceful_shutdown(server)
