
import logging
import random

import requests

import hls_playlist


logger = logging.getLogger(__name__)


def get_master_playlist(channel, session=requests):
	"""Get the master playlist for given channel from twitch"""
	resp = session.get(
		"https://api.twitch.tv/api/channels/{}/access_token.json".format(channel),
		params={'as3': 't'},
		headers={
			'Accept': 'application/vnd.twitchtv.v3+json',
			'Client-ID': 'pwkzresl8kj2rdj6g7bvxl9ys1wly3j',
		},
	)
	resp.raise_for_status() # getting access token
	token = resp.json()
	resp = session.get(
		"https://usher.ttvnw.net/api/channel/hls/{}.m3u8".format(channel),
		params={
			# Taken from streamlink. Unsure what's needed and what changing things can do.
			"player": "twitchweb",
			"p": random.randrange(1000000),
			"type": "any",
			"allow_source": "true",
			"allow_audio_only": "true",
			"allow_spectre": "false",
			"fast_bread": "True",
			"sig": token["sig"],
			"token": token["token"],
			# Also observed in the wild but not used in streamlink:
			# "playlist_include_framerate": "true"
			# "reassignments_supported": "true"
			# It's reported that setting this may affect whether you get ads, but this is
			# in flux. Better to just blend in with the crowd for now.
			# "platform": "_"
		},
	)
	resp.raise_for_status() # getting master playlist
	playlist = hls_playlist.load(resp.text, base_uri=resp.url)
	return playlist


def get_media_playlist_uris(master_playlist, target_qualities):
	"""From a master playlist, extract URIs of media playlists of interest.
	Returns {stream name: uri}.
	Note this is not a general method for all HLS streams, and makes twitch-specific assumptions,
	though we try to check and emit warnings if these assumptions are broken.
	"""
	# Twitch master playlists are observed to have the following form:
	#   The first listed variant is the source playlist and has "(source)" in the name.
	#   Other variants are listed in order of quality from highest to lowest, followed by audio_only.
	#   These transcoded variants are named "Hp[R]" where H is the vertical resolution and
	#   optionally R is the frame rate. R is elided if == 30. Examples: 720p60, 720p, 480p, 360p, 160p
	#   These variants are observed to only ever have one rendition, type video, which contains the name
	#   but no URI. The URI in the main variant entry is the one to use. This is true even of the
	#   "audio_only" stream.
	#   Streams without transcoding options only show source and audio_only.
	# We return the source stream in addition to any in target_qualities that is found.

	def variant_name(variant):
		names = set(media.name for media in variant.media if media.type == "VIDEO" and media.name)
		if not names:
			logger.warning("Variant {} has no named video renditions, can't determine name".format(variant))
			return None
		if len(names) > 1:
			logger.warning("Variant {} has multiple possible names, picking one arbitrarily".format(variant))
		return list(names)[0]

	if not master_playlist.playlists:
		raise ValueError("Master playlist has no variants")

	for variant in master_playlist.playlists:
		if any(media.uri for media in variant.media):
			logger.warning("Variant has a rendition with its own URI: {}".format(variant))

	by_name = {variant_name(variant): variant for variant in master_playlist.playlists}

	source_candidates = [name for name in by_name.keys() if "(source)" in name]
	if len(source_candidates) != 1:
		raise ValueError("Can't find source stream, not exactly one candidate. Candidates: {}, playlist: {}".format(
			source_candidates, master_playlist,
		))
	source = by_name[source_candidates[0]]

	variants = {name: variant for name, variant in by_name.items() if name in target_qualities}
	variants["source"] = source

	return {name: variant.uri for name, variant in variants.items()}


def get_media_playlist(uri, session=requests):
	resp = session.get(uri)
	resp.raise_for_status()
	return hls_playlist.load(resp.text, base_uri=resp.url)
