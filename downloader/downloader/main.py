
import hashlib
import logging
import os
import time
from base64 import b64encode

import twitch


def download_segments(base_dir, name, uri):
	# NOTE: This function is not written to be resilient, do not rely on it.
	# There's no retry, no atomic rename for file writing, file name format is bad,
	# skips segments with missing info, doesn't confirm lengths, other issues.
	# Doesn't use monotonic time.
	INTERVAL = 2
	prev_segments = []
	while True:
		last_check = time.time()
		logging.info("Getting playlist")
		playlist = twitch.get_media_playlist(uri)
		for segment in playlist.segments:
			if segment.uri in prev_segments:
				continue
			if not segment.date:
				logging.warning("Segment has no date given, skipping")
				continue
			segment_data = twitch.get_segment(segment.uri)
			segment_hash = hashlib.sha256(segment_data).digest()
			filename = os.path.join(
				base_dir, name,
				"{}-{}".format(segment.date, segment.duration),
				"{}.ts".format(b64encode(segment_hash, "-_")),
			)
			logging.info("Writing segment {}".format(filename))
			if not os.path.exists(os.path.dirname(filename)):
				os.makedirs(os.path.dirname(filename))
			with open(filename, 'w') as f:
				f.write(segment_data)
		prev_segments = [segment.uri for segment in playlist.segments]
		# Wait up to 2s until 2s after last_check
		elapsed = time.time() - last_check
		time.sleep(max(0, INTERVAL - elapsed))


def main(channel, base_dir=".", qualities=""):
	qualities = qualities.split(",") if qualities else []
	master_playlist = twitch.get_master_playlist(channel)
	uris = twitch.get_media_playlist_uris(master_playlist, qualities)
	if len(uris) != 1:
		raise NotImplementedError
	(name, uri), = uris.items()
	download_segments(base_dir, name, uri)
