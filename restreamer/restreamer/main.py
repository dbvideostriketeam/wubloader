
import datetime
import errno
import functools
import json
import logging
import os
import signal

import dateutil.parser
import gevent
from flask import Flask, url_for, request, abort
from gevent.pywsgi import WSGIServer

from common import get_best_segments

import generate_hls


app = Flask('restreamer', static_url_path='/segments')


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


@app.route('/files/<stream>/<variant>')
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
	return dateutil.parser.parse(first), dateutil.parser.parse(last) + datetime.timedelta(hours=1)


@app.route('/playlist/<stream>.m3u8')
@has_path_args
def generate_master_playlist(stream):
	"""Returns a HLS master playlist for the given stream.
	Takes optional params:
		start, end: The time to begin and end the stream at.
			See generate_media_playlist for details.
	"""
	start = dateutil.parser.parse(request.args['start']) if 'start' in request.args else None
	end = dateutil.parser.parse(request.args['end']) if 'end' in request.args else None
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
@has_path_args
def generate_media_playlist(stream, variant):
	"""Returns a HLS media playlist for the given stream and variant.
	Takes optional params:
		start, end: The time to begin and end the stream at.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS).
			If not given, effectively means "infinity", ie. no start means
			any time ago, no end means any time in the future.
	"""

	hours_path = os.path.join(app.static_folder, stream, variant)
	if not os.path.isdir(hours_path):
		abort(404)

	start = dateutil.parser.parse(request.args['start']) if 'start' in request.args else None
	end = dateutil.parser.parse(request.args['end']) if 'end' in request.args else None
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


def main(host='0.0.0.0', port=8000, base_dir='.'):
	app.static_folder = base_dir
	server = WSGIServer((host, port), app)

	def stop():
		logging.info("Shutting down")
		server.stop()
	gevent.signal(signal.SIGTERM, stop)

	logging.info("Starting up")
	server.serve_forever()
	logging.info("Gracefully shut down")
