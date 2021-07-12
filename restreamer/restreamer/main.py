
import datetime
import errno
import functools
import json
import logging
import os
import signal

import gevent
import gevent.backdoor
import prometheus_client as prom
from flask import Flask, url_for, request, abort, redirect, Response
from gevent.pywsgi import WSGIServer

from common import dateutil, get_best_segments, rough_cut_segments, smart_cut_segments, fast_cut_segments, full_cut_segments, PromLogCountsHandler, install_stacksampler
from common.flask_stats import request_stats, after_request

import generate_hls
from .review import review, NoSegments, RaceNotFound, CantFindStart


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
	Disallows hidden folders and path traversal, and converts unicode to bytes.
	"""
	@functools.wraps(fn)
	def _has_path_args(**kwargs):
		kwargs = {key: value.encode('utf-8') for key, value in kwargs.items()}
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
	"""Returns a JSON list of segment files for a given channel, quality and
	hour. Returns empty list on non-existant channels, etc.
	"""
	path = os.path.join(
		app.static_folder,
		channel,
		quality,
		hour,
	)
	return json.dumps(listdir(path, error=False))


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
	Note that because it returns segments _covering_ that range, the playlist
	may start slightly before and end slightly after the given times.
	"""

	hours_path = os.path.join(app.static_folder, channel, quality)
	if not os.path.isdir(hours_path):
		abort(404)

	start = dateutil.parse_utc_only(request.args['start']) if 'start' in request.args else None
	end = dateutil.parse_utc_only(request.args['end']) if 'end' in request.args else None
	if start is None or end is None:
		# If start or end are not given, use the earliest/latest time available
		first, last = time_range_for_quality(channel, quality)
		if start is None:
			start = first
		if end is None:
			end = last

	# get_best_segments requires start be before end, special case that as no segments
	# (not an error because someone might ask for a specific start, no end, but we ended up with
	# end before start because that's the latest time we have)
	if start < end:
		segments = get_best_segments(hours_path, start, end)
	else:
		# Note the None to indicate there was a "hole" at both start and end
		segments = [None]

	return generate_hls.generate_media(segments, os.path.join(app.static_url_path, channel, quality))


@app.route('/replay/<stream>/<variant>.m3u8')
@has_path_args
def replay(stream, variant):
	hours_path = os.path.join(app.static_folder, stream, variant)

	start = datetime.datetime.utcnow() - datetime.timedelta(seconds=20)
	end = datetime.datetime.utcnow() - datetime.timedelta(seconds=5)

	if os.path.isdir(hours_path):
		segments = get_best_segments(hours_path, start, end)
	else:
		segments = [None]
	if segments == [None]:
		print "No replay, serving placeholder"
		stream, variant = 'ekimekim', 'source'
		segments = get_best_segments(os.path.join(app.static_folder, stream, variant),
			datetime.datetime(2021, 1, 24, 22, 51, 45),
			datetime.datetime(2021, 1, 24, 22, 52, 15),
		)
		assert segments != [None], "missing placeholder"
	return generate_hls.generate_media(segments, os.path.join(app.static_url_path, stream, variant))


@app.route('/cut/<channel>/<quality>.ts')
@request_stats
@has_path_args
def cut(channel, quality):
	"""Return a MPEGTS video file covering the exact timestamp range.
	Params:
		start, end: Required. The start and end times, down to the millisecond.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
		allow_holes: Optional, default false. If false, errors out with a 406 Not Acceptable
			if any holes are detected, rather than producing a video with missing parts.
			Set to true by passing "true" (case insensitive).
			Even if holes are allowed, a 406 may result if the resulting video would be empty.
		type: One of:
			"rough": A direct concat, like a fast cut but without any ffmpeg.
				It may extend beyond the requested start and end times by a few seconds.
			"fast": Very fast but with minor artifacting where the first and last segments join
				the other segments.
			"mpegts": A full cut to a streamable mpegts format. This consumes signifigant server
				resources, so please use sparingly.
			"mp4": As mpegts, but encodes as MP4. This format must be buffered to disk before
				sending so it's a bit slower.
	"""
	start = dateutil.parse_utc_only(request.args['start']) if 'start' in request.args else None
	end = dateutil.parse_utc_only(request.args['end']) if 'end' in request.args else None
	if start is None or end is None:
		# If start or end are not given, use the earliest/latest time available
		first, last = time_range_for_quality(channel, quality)
		if start is None:
			start = first
		if end is None:
			end = last

	if end <= start:
		return "End must be after start", 400

	allow_holes = request.args.get('allow_holes', 'false').lower()
	if allow_holes not in ["true", "false"]:
		return "allow_holes must be one of: true, false", 400
	allow_holes = (allow_holes == "true")

	hours_path = os.path.join(app.static_folder, channel, quality)
	if not os.path.isdir(hours_path):
		abort(404)

	segments = get_best_segments(hours_path, start, end)
	if not allow_holes and None in segments:
		return "Requested time range contains holes or is incomplete.", 406

	if not any(segment is not None for segment in segments):
		return "We have no content available within the requested time range.", 406

	type = request.args.get('type', 'fast')
	if type == 'rough':
		return Response(rough_cut_segments(segments, start, end), mimetype='video/MP2T')
	elif type == 'fast':
		return Response(fast_cut_segments(segments, start, end), mimetype='video/MP2T')
	elif type == 'smart':
		return Response(smart_cut_segments(segments, start, end), mimetype='video/MP2T')
	elif type in ('mpegts', 'mp4'):
		if type == 'mp4':
			return "mp4 type has been disabled due to the load it causes", 400
		# encode as high-quality, without wasting too much cpu on encoding
		stream, muxer, mimetype = (True, 'mpegts', 'video/MP2T') if type == 'mpegts' else (False, 'mp4', 'video/mp4')
		encoding_args = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-f', muxer]
		return Response(full_cut_segments(segments, start, end, encoding_args, stream=stream), mimetype=mimetype)
	else:
		return "Unknown type {!r}".format(type), 400


@app.route('/generate_videos/<channel>/<quality>.ts')
@request_stats
@has_path_args
def generate_videos(channel, quality):
	"""Generate one video for each contiguous range of segments (ie. split at holes),
	and save them as CHANNEL_QUALITY_N.ts in the segments directory.
	"""
	start, end = time_range_for_quality(channel, quality)
	hours_path = os.path.join(app.static_folder, channel, quality)
	if not os.path.isdir(hours_path):
		abort(404)

	segments = get_best_segments(hours_path, start, end)
	contiguous = []
	n = [0]

	def write_file():
		if not contiguous:
			return
		with open(os.path.join(app.static_folder, "{}_{}_{}.ts".format(channel, quality, n[0])), 'w') as f:
			for chunk in rough_cut_segments(contiguous, start, end):
				f.write(chunk)
		n[0] += 1

	for segment in segments:
		if segment is not None:
			contiguous.append(segment)
			continue
		write_file()
		contiguous = []
	write_file()


@app.route('/review/<match_id>/<race_number>')
@request_stats
def review_race(match_id, race_number):
	"""Cut a condor race review for given match id and race number.
	Params:
		start_range: Two numbers, comma-seperated. How long before and after the nominal
			race start time to look for the start signal. Default 0,5.
		finish_range: As start_range, but how long to make the final review video before/after
			the nominal duration. Default -5,10.
		racer1_start, racer2_start: Explicit start times, as float.
	"""
	if app.condor_db is None:
		return "Reviews are disabled", 501
	start_range = map(float, request.args.get('start_range', '0,5').split(','))
	finish_range = map(float, request.args.get('finish_range', '-5,10').split(','))
	racer1_start = float(request.args['racer1_start']) if 'racer1_start' in request.args else None
	racer2_start = float(request.args['racer2_start']) if 'racer2_start' in request.args else None
	try:
		review_path = review(
			match_id, race_number, app.static_folder, app.condor_db, start_range, finish_range,
			racer1_start, racer2_start,
		)
	except RaceNotFound as e:
		return str(e), 404
	except NoSegments:
		logging.warning("Failed review due to no segments", exc_info=True)
		return "Video content is missing - cannot review automatically", 400
	except CantFindStart as e:
		return (
			"{}\n"
			"Please check start video and adjust start_range or set racer{}_start: {}\n"
			"Note timestamps in that video are only valid for the current start_range.\n"
		).format(
			e, e.racer_number, os.path.join(app.static_url_path, os.path.relpath(e.path, app.static_folder))
		), 400

	relative_path = os.path.relpath(review_path, app.static_folder)
	review_url = os.path.join(app.static_url_path, relative_path)
	response = redirect(review_url)
	response.autocorrect_location_header = False
	return response


def main(host='0.0.0.0', port=8000, base_dir='.', backdoor_port=0, condor_db=None):
	app.static_folder = base_dir
	app.condor_db = condor_db
	server = WSGIServer((host, port), cors(app))

	def stop():
		logging.info("Shutting down")
		server.stop()
	gevent.signal_handler(signal.SIGTERM, stop)

	PromLogCountsHandler.install()
	install_stacksampler()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	logging.info("Starting up")
	server.serve_forever()
	logging.info("Gracefully shut down")
