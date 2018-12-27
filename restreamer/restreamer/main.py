
import errno
import functools
import json
import os

import dateutil.parser
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


@app.route('/playlist/<stream>.m3u8')
@has_path_args
def generate_master_playlist(stream):
	"""Returns a HLS master playlist for the given stream.
	Takes optional params:
		start, end: The time to begin and end the stream at.
			See generate_media_playlist for details.
	"""
	variants = listdir(os.path.join(app.static_folder, stream))
	playlists = {
		variant: url_for('generate_media_playlist', stream=stream, variant=variant, **request.args)
		for variant in variants
	}
	return generate_hls.generate_master(playlists)


@app.route('/playlist/<stream>/<variant>.m3u8')
@has_path_args
def generate_media_playlist(stream, variant):
	#TODO handle no start/end
	#TODO error handling of args
	# TODO lots of other stuff
	start = dateutil.parser.parse(request.args['start'])
	end = dateutil.parser.parse(request.args['end'])
	hours_path = os.path.join(app.static_folder, stream, variant)
	segments = get_best_segments(hours_path, start, end)
	return generate_hls.generate_media(segments, os.path.join(app.static_url_path, stream, variant))


def main(host='0.0.0.0', port=8000, base_dir='.'):
	app.static_folder = base_dir
	server = WSGIServer((host, port), app)
	server.serve_forever()
