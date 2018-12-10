
import errno
import json
import os

from flask import Flask, url_for, request, abort
from gevent.pywsgi import WSGIServer

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


@app.route('/files/<stream>/<variant>/<hour>')
def list_segments(stream, variant, hour):
	"""Returns a JSON list of segment files for a given stream, variant and hour.
	Returns empty list on non-existant streams, etc.
	"""
	# Check no-one's being sneaky with path traversal or hidden folders
	if any(arg.startswith('.') for arg in (stream, variant, hour)):
		return "Parts may not start with period", 403
	path = os.path.join(
		app.static_folder,
		stream,
		variant,
		hour,
	)
	return json.dumps(listdir(path, error=False))


@app.route('/playlist/<stream>.m3u8')
def generate_master_playlist(stream):
	"""Returns a HLS master playlist for the given stream.
	Takes optional params:
		start, end: The time to begin and end the stream at.
			See generate_media_playlist for details.
	"""
	# path traversal / hidden folders
	if stream.startswith('.'):
		return "Stream may not start with period", 403
	variants = listdir(os.path.join(app.static_folder, stream))
	playlists = {
		variant: url_for('generate_media_playlist', stream=stream, variant=variant, **request.args)
		for variant in variants
	}
	return generate_hls.generate_master(playlists)


@app.route('/playlist/<stream>/<variant>.m3u8')
def generate_media_playlist(stream, variant):
	# TODO
	return "Not Implemented", 501


def main(host='0.0.0.0', port=8000, base_dir='.'):
	app.static_folder = base_dir
	server = WSGIServer((host, port), app)
	server.serve_forever()
