
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
from flask import Flask, url_for, request, abort, Response
from gevent.pywsgi import WSGIServer

import common.dateutil
from common import get_best_segments, cut_segments, PromLogCountsHandler, install_stacksampler

import generate_hls
from stats import stats, after_request


app = Flask('restreamer', static_url_path='/segments')
app.after_request(after_request)


"""
The restreamer is a simple http api for listing available segments and generating
HLS playlists for them.

The segments themselves are ideally to be served by some external webserver
under "/segments/<stream>/<variant>/<hour>/<filename>" (ie. with BASE_DIR under "/segments"),
though this server will also serve them if requested.
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
@stats
def metrics():
	"""Return current metrics in prometheus metrics format"""
	return prom.generate_latest()

@app.route('/files')
@stats
def list_streams():
	"""Returns a JSON list of streams for which there may be segments available.
	Returns empty list if no streams are available.
	"""
	path = app.static_folder
	return json.dumps(listdir(path, error=False))


@app.route('/files/<stream>')
@stats
@has_path_args
def list_variants(stream):
	"""Returns a JSON list of variants for the given stream for which there may
	be segments available. Returns empty list on non-existent streams, etc.
	"""
	path = os.path.join(
		app.static_folder,
		stream,
	)
	return json.dumps(listdir(path, error=False))

@app.route('/files/<stream>/<variant>')
@stats
@has_path_args
def list_hours(stream, variant):
	"""Returns a JSON list of hours for the given stream and variant for which
	there may be segments available. Returns empty list on non-existent streams, etc.
	"""
	path = os.path.join(
		app.static_folder,
		stream,
		variant,
	)
	return json.dumps(listdir(path, error=False))


@app.route('/files/<stream>/<variant>/<hour>')
@stats
@has_path_args
def list_segments(stream, variant, hour):
	"""Returns a JSON list of segment files for a given stream, variant and hour.
	Returns empty list on non-existant streams, etc.
	"""
	path = os.path.join(
		app.static_folder,
		stream,
		variant,
		hour,
	)
	return json.dumps(listdir(path, error=False))


def time_range_for_variant(stream, variant):
	"""Returns earliest and latest times that the given variant has segments for
	(up to hour resolution), or 404 if it doesn't exist / is empty."""
	hours = listdir(os.path.join(app.static_folder, stream, variant))
	if not hours:
		abort(404)
	first, last = min(hours), max(hours)
	# note last hour parses to _start_ of that hour, so we add 1h to go to end of that hour
	def parse_hour(s):
		return datetime.datetime.strptime(s, "%Y-%m-%dT%H")
	return parse_hour(first), parse_hour(last) + datetime.timedelta(hours=1)


@app.route('/playlist/<stream>.m3u8')
@stats
@has_path_args
def generate_master_playlist(stream):
	"""Returns a HLS master playlist for the given stream.
	Takes optional params:
		start, end: The time to begin and end the stream at.
			See generate_media_playlist for details.
	"""
	start = common.dateutil.parse_utc_only(request.args['start']) if 'start' in request.args else None
	end = common.dateutil.parse_utc_only(request.args['end']) if 'end' in request.args else None
	variants = listdir(os.path.join(app.static_folder, stream))

	playlists = {}
	for variant in variants:
		# If start or end are given, try to restrict offered variants to ones which exist for that
		# time range.
		if start is not None or end is not None:
			first, last = time_range_for_variant(stream, variant)
			if start is not None and last < start:
				continue # last time for variant is before our start time, don't offer variant
			if end is not None and end < first:
				continue # our end time is before first time for variant, don't offer variant
		playlists[variant] = url_for(
			'generate_media_playlist', stream=stream, variant=variant, **request.args
		)

	return generate_hls.generate_master(playlists)


@app.route('/playlist/<stream>/<variant>.m3u8')
@stats
@has_path_args
def generate_media_playlist(stream, variant):
	"""Returns a HLS media playlist for the given stream and variant.
	Takes optional params:
		start, end: The time to begin and end the stream at.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
			If not given, effectively means "infinity", ie. no start means
			any time ago, no end means any time in the future.
	Note that because it returns segments _covering_ that range, the playlist
	may start slightly before and end slightly after the given times.
	"""

	hours_path = os.path.join(app.static_folder, stream, variant)
	if not os.path.isdir(hours_path):
		abort(404)

	start = common.dateutil.parse_utc_only(request.args['start']) if 'start' in request.args else None
	end = common.dateutil.parse_utc_only(request.args['end']) if 'end' in request.args else None
	if start is None or end is None:
		# If start or end are not given, use the earliest/latest time available
		first, last = time_range_for_variant(stream, variant)
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

	return generate_hls.generate_media(segments, os.path.join(app.static_url_path, stream, variant))


@app.route('/cut/<stream>/<variant>.ts')
@stats
@has_path_args
def cut(stream, variant):
	"""Return a MPEGTS video file covering the exact timestamp range.
	Params:
		start, end: Required. The start and end times, down to the millisecond.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS) and UTC.
		allow_holes: Optional, default false. If false, errors out with a 406 Not Acceptable
			if any holes are detected, rather than producing a video with missing parts.
			Set to true by passing "true" (case insensitive).
			Even if holes are allowed, a 406 may result if the resulting video would be empty.
	"""
	start = common.dateutil.parse_utc_only(request.args['start'])
	end = common.dateutil.parse_utc_only(request.args['end'])
	if end <= start:
		return "End must be after start", 400

	allow_holes = request.args.get('allow_holes', 'false').lower()
	if allow_holes not in ["true", "false"]:
		return "allow_holes must be one of: true, false", 400
	allow_holes = (allow_holes == "true")

	hours_path = os.path.join(app.static_folder, stream, variant)
	if not os.path.isdir(hours_path):
		abort(404)

	segments = get_best_segments(hours_path, start, end)
	if not allow_holes and None in segments:
		return "Requested time range contains holes or is incomplete.", 406

	if not any(segment is not None for segment in segments):
		return "We have no content available within the requested time range.", 406

	return Response(cut_segments(segments, start, end), mimetype='video/MP2T')


def main(host='0.0.0.0', port=8000, base_dir='.', backdoor_port=0):
	app.static_folder = base_dir
	server = WSGIServer((host, port), cors(app))

	def stop():
		logging.info("Shutting down")
		server.stop()
	gevent.signal(signal.SIGTERM, stop)

	PromLogCountsHandler.install()
	install_stacksampler()

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	logging.info("Starting up")
	server.serve_forever()
	logging.info("Gracefully shut down")
