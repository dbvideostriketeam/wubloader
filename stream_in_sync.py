
from datetime import datetime, timedelta


def pipe_stream(racer, start):
	"""Returns a pipe streaming racer's video, starting from given start timestamp."""
	# TODO this is basically a specialized version of fast_cut_segments with no end point
	# that polls for new segments.


def sync_stream(racer, start):
	"""Returns a pipe streaming racer's video, starting from the point they started.
	Starts searching from given start timestamp.
	Blocks until start found.
	"""
	# TODO send pipe_stream(racer, start) to ffmpeg until blackdetect found,
	# then return pipe_stream(racer, start + blackdetect)


def main(racer1, racer2, start=0):
	"""
		start:
			0: now
			< 0: seconds ago
			> 0: unix timestamp
	"""
	if start > 0:
		start = datetime.utcfromtimestamp(start)
	else:
		start = datetime.utcnow() + timedelta(seconds=start)

	stream1, stream2 = gevent.Pool.Group().map(lambda r: sync_stream(r, start), [racer1, racer2])
	# TODO multiplex stream1, stream2 and timer (using drawtext) into one video
