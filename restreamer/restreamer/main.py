
import datetime
import errno
import functools
import json
import logging
import os
import shutil
import signal
from contextlib import closing

import dateutil.parser
import gevent
from flask import Flask, url_for, request, abort, Response
from gevent import subprocess
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
	Note that because it returns segments _covering_ that range, the playlist
	may start slightly before and end slightly after the given times.
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


@app.route('/cut/<stream>/<variant>.ts')
@has_path_args
def cut(stream, variant):
	"""Return a MPEGTS video file covering the exact timestamp range.
	Params:
		start, end: Required. The start and end times, down to the millisecond.
			Must be in ISO 8601 format (ie. yyyy-mm-ddTHH:MM:SS).
		allow_holes: Optional, default false. If false, errors out with a 406 Not Acceptable
			if any holes are detected, rather than producing a video with missing parts.
			Set to true by passing "true" (case insensitive).
			Even if holes are allowed, a 406 may result if the resulting video would be empty.
		experimental: Optional, default false. If true, use the new, much faster, but experimental
			method of cutting.
	"""
	start = dateutil.parser.parse(request.args['start'])
	end = dateutil.parser.parse(request.args['end'])
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

	segments = [segment for segment in segments if segment is not None]

	if not segments:
		return "We have no content available within the requested time range.", 406

	# how far into the first segment to begin
	cut_start = max(0, (segments[0].start - start).total_seconds())
	# calculate full uncut duration of content, ie. without holes.
	full_duration = sum(segment.duration.total_seconds() for segment in segments)
	# calculate how much of final segment should be cut off
	cut_end = max(0, (end - segments[-1].end).total_seconds())
	# finally, calculate actual output duration, which is what ffmpeg will use
	duration = full_duration - cut_start - cut_end

	# possibly defer to experiemntal version now that we've parsed our inputs.
	# we'll clean up this whole flow later.
	if request.args.get('experimental') == 'true':
		return cut_experimental(segments, cut_start, cut_end)

	def feed_input(pipe):
		# pass each segment into ffmpeg's stdin in order, while outputing everything on stdout.
		for segment in segments:
			with open(segment.path) as f:
				shutil.copyfileobj(f, pipe)
		pipe.close()

	def _cut():
		ffmpeg = None
		input_feeder = None
		try:
			ffmpeg = subprocess.Popen([
				"ffmpeg",
				"-i", "-", # read from stdin
				"-ss", str(cut_start), # seconds to cut from start
				"-t", str(duration), # total duration, which says when to cut at end
				"-f", "mpegts", # output as MPEG-TS format
				"-", # output to stdout
			], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
			input_feeder = gevent.spawn(feed_input, ffmpeg.stdin)
			# stream the output until it is closed
			while True:
				chunk = ffmpeg.stdout.read(16*1024)
				if not chunk:
					break
				yield chunk
			# check if any errors occurred in input writing, or if ffmpeg exited non-success.
			# raising an error mid-streaming-response will get flask to abort the response
			# uncleanly, which tells the client that something went wrong.
			if ffmpeg.wait() != 0:
				raise Exception("Error while streaming cut: ffmpeg exited {}".format(ffmpeg.returncode))
			input_feeder.get() # re-raise any errors from feed_input()
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

	return Response(_cut(), mimetype='video/MP2T')


def cut_experimental(segments, cut_start, cut_end):
	"""Experimental cutting method where we cut the first and last segments only,
	then cat them all together."""
	# Note: assumes codecs don't change from segment to segment.

	def streams_info(segment):
		"""Return ffprobe's info on streams as a list of dicts"""
		output = subprocess.check_output(['ffprobe', '-of', 'json', '-show_streams', segment.path])
		return json.loads(output)['streams']

	def ffmpeg(segment, cut_start=None, cut_end=None):
		"""Return a Popen object which is ffmpeg cutting the given segment"""
		args = ['ffmpeg', '-i', segment.path]
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

	def chunks(fileobj, chunk_size=16*1024):
		"""Read fileobj until EOF, yielding chunk_size sized chunks of data."""
		while True:
			chunk = fileobj.read(chunk_size)
			if not chunk:
				break
			yield chunk

	def _cut():
		# set first and last only if they actually need cutting
		first = segments[0] if cut_start else None
		last = segments[-1] if cut_end else None
		for segment in segments:
			# note first and last might be the same segment.
			# note a segment will only match if cutting actually needs to be done
			# (ie. cut_start or cut_end is not 0)
			if segment in (first, last):
				proc = None
				try:
					proc = ffmpeg(
						segment,
						cut_start if segment == first else None,
						cut_end if segment == last else None,
					)
					with closing(proc.stdout):
						for chunk in chunks(proc.stdout):
							yield chunk
					proc.wait()
				except Exception:
					# try to clean up proc, ignoring errors
					try:
						proc.kill()
					except OSError:
						pass
				else:
					# check if ffmpeg had errors
					if proc.returncode != 0:
						raise Exception(
							"Error while streaming cut: ffmpeg exited {}".format(proc.returncode)
						)
			else:
				# no cutting needed, just serve the file
				with open(segment.path) as f:
					for chunk in chunks(f):
						yield chunk

	return Response(_cut(), mimetype='video/MP2T')



def main(host='0.0.0.0', port=8000, base_dir='.'):
	app.static_folder = base_dir
	server = WSGIServer((host, port), cors(app))

	def stop():
		logging.info("Shutting down")
		server.stop()
	gevent.signal(signal.SIGTERM, stop)

	logging.info("Starting up")
	server.serve_forever()
	logging.info("Gracefully shut down")
