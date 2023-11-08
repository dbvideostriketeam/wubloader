
import logging
import random

from common.requests import InstrumentedSession

from . import hls_playlist


class Provider:
	"""Base class with defaults, to be overriden for specific providers"""

	# How long (in seconds) we should keep using a media playlist URI before getting a new one.
	# This matters because some providers set an expiry on the URI they give you.
	# However the default is an arbitrarily long period (ie. never).
	MAX_WORKER_AGE = 30 * 24 * 60 * 60 # 30 days

	def get_media_playlist_uris(self, qualities, session=None):
		"""Fetches master playlist and returns {quality: media playlist URI} for each
		requested quality."""
		raise NotImplementedError

	def get_media_playlist(self, uri, session=None):
		"""Fetches the given media playlist. In most cases this is just a simple fetch
		and doesn't need to be overriden."""
		if session is None:
			session = InstrumentedSession()
		resp = session.get(uri, metric_name='get_media_playlist')
		resp.raise_for_status()
		return hls_playlist.load(resp.text, base_uri=resp.url)


class URLProvider(Provider):
	"""Provider that takes an arbitrary master playlist URL.
	Doesn't support multiple renditions, quality must be "source".
	"""
	def __init__(self, master_playlist_url):
		self.master_playlist_url = master_playlist_url

	def get_media_playlist_uris(self, qualities, session=None):
		if qualities != ["source"]:
			raise ValueError("Cannot provide non-source qualities")
		if session is None:
			session = InstrumentedSession()

		resp = session.get(self.master_playlist_url, metric_name='url_master_playlist')
		resp.raise_for_status()
		master_playlist = hls_playlist.load(resp.text, base_uri=resp.url)

		# Take the first variant
		return {"source": master_playlist.playlists[0].uri}


class TwitchProvider(Provider):
	"""Provider that takes a twitch channel."""
	# Twitch links expire after 24h, so roll workers at 20h
	MAX_WORKER_AGE = 20 * 60 * 60

	def __init__(self, channel, auth_token=None):
		self.channel = channel
		self.auth_token = auth_token

	def get_access_token(self, session):
		request = {
			"operationName": "PlaybackAccessToken",
			"extensions": {
				"persistedQuery": {
					"version": 1,
					"sha256Hash": "0828119ded1c13477966434e15800ff57ddacf13ba1911c129dc2200705b0712"
				}
			},
			"variables": {
				"isLive": True,
				"login": self.channel,
				"isVod": False,
				"vodID": "",
				"playerType": "site"
			}
		}
		headers = {'Client-ID': 'kimne78kx3ncx6brgo4mv6wki5h1ko'}
		if self.auth_token is not None:
			headers["Authorization"] = "OAuth {}".format(self.auth_token)
		resp = session.post(
			"https://gql.twitch.tv/gql",
			json=request,
			headers=headers,
			metric_name='twitch_get_access_token',
		)
		resp.raise_for_status()
		data = resp.json()["data"]["streamPlaybackAccessToken"]
		return data['signature'], data['value']

	def get_master_playlist(self, session):
		sig, token = self.get_access_token(session)
		resp = session.get(
			"https://usher.ttvnw.net/api/channel/hls/{}.m3u8".format(self.channel),
			headers={
				"referer": "https://player.twitch.tv",
				"origin": "https://player.twitch.tv",
			},
			params={
				# Taken from streamlink. Unsure what's needed and what changing things can do.
				"player": "twitchweb",
				"p": random.randrange(1000000),
				"type": "any",
				"allow_source": "true",
				"allow_audio_only": "true",
				"allow_spectre": "false",
				"fast_bread": "true",
				"sig": sig,
				"token": token,
			},
			metric_name='twitch_get_master_playlist',
		)
		resp.raise_for_status() # getting master playlist
		playlist = hls_playlist.load(resp.text, base_uri=resp.url)
		return playlist

	def get_media_playlist_uris(self, target_qualities, session=None):
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

		logger = logging.getLogger("twitch")
		if session is None:
			session = InstrumentedSession()

		master_playlist = self.get_master_playlist(session)

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
