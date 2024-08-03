
import logging
import json
import signal

import argh
import gevent
import gevent.backdoor
import gevent.event
import prometheus_client as prom

import common
from common.database import DBManager, query
from common.googleapis import GoogleAPIClient


PlaylistConfig = namedtuple("Playlist", ["tags", "first_event_id", "last_event_id"])
PlaylistEntry = namedtuple("PlaylistEntry", ["entry_id", "video_id"])


class PlaylistOutdated(Exception):
	"""Thrown when a function detects the playlist is not in the state we think it is.
	This can be safely ignored or used to trigger a retry after refreshing the state."""


class APIException(Exception):
	"""Thrown when an API call fails. Exposes the HTTP status code."""
	def __init__(self, message, code):
		super().__init__(message)
		self.code = code


class PlaylistManager(object):

	def __init__(self, dbmanager, api_client, upload_locations, playlist_tags):
		self.dbmanager = dbmanager
		self.api = YoutubeAPI(api_client)
		self.upload_locations = upload_locations
		self.static_playlist_tags = playlist_tags
		self.reset()

	def reset(self, playlist_id=None):
		"""Called to clear saved state and force a refresh after errors.
		Either reset a specific playlist, or all if no arg given.
		"""
		if playlist_id is None:
			# playlist_state represents our mirrored view of the list of items in each playlist.
			# If a playlist is not present, it means we need to refresh our view of it.
			# {playlist_id: [PlaylistEntry]}
			self.playlist_state = {}
		else:
			self.playlist_state.pop(playlist_id, None)

	def get_playlist(self, playlist_id):
		"""Returns our cached copy of the list of playlist entries."""
		return self.playlist_state.get(playlist_id, [])

	def run_once(self):
		"""Do one check of all videos and playlists.
		At a high level:
			Fetch all eligible videos from the database
			Group them into playlists depending on their tags
			For each playlist, concurrently:
				Compare this generated playlist to our local copy of the real thing
				If they match, do nothing (don't even bother checking the real thing)
				Check real thing for total length. If it matches, assume we're good. Otherwise refresh.
				For each video to add:
					Determine correct point in sort order
					Add to playlist
					Update local mirror with the action we just performed
		"""
		logging.info("Checking for new videos")
		videos = self.get_videos()
		logging.debug(f"Found {len(videos)} eligible videos")

		logging.info("Getting dynamic playlists")
		playlists = self.get_playlist_config()
		logging.debug(f"Found {len(playlists)} playlists")

		# start all workers
		workers = {}
		for playlist_id, playlist_config in playlists.items():
			workers[playlist_id] = gevent.spawn(self.update_playlist, playlist_id, playlist_config, videos)

		# check each one for success, reset on failure
		for playlist_id, worker in workers.items():
			try:
				worker.get()
			except Exception:
				logging.exception(f"Failed to update playlist {playlist_id}")
				self.reset(playlist_id)

	def get_videos(self):
		# Most of the time by getting then re-putting the conn, we'll just use the same
		# one every time. But if there's an error we won't re-put it so we'll get a new one
		# the next time.
		conn = self.dbmanager.get_conn()
		videos = query(conn, """
			SELECT video_id, tags, COALESCE((video_ranges[1]).start, event_start) AS start_time
			FROM events
			WHERE state = 'DONE' AND upload_location = ANY (%s) AND public
		""", self.upload_locations)
		self.dbmanager.put_conn(conn)
		return {video.video_id: video for video in videos}

	def get_playlist_config(self):
		conn = self.dbmanager.get_conn()
		playlists = {
			row.playlist_id: PlaylistConfig(
				[tag.lower() for tag in row.tags],
				row.first_event_id,
				row.last_event_id,
			) for row in query(conn, "SELECT playlist_id, tags, first_event_id, last_event_id FROM playlists")
		}
		self.dbmanager.put_conn(conn)
		duplicates = set(playlists) & set(self.static_playlists)
		if duplicates:
			raise ValueError(
				"Some playlists are listed in both static and dynamic playlist sources: {}".format(", ".join(duplicates))
			)
		playlists.update({
			id: PlaylistConfig(tags, None, None)
			for id, tags in self.static_playlists.items()
		})
		return playlists

	def update_playlist(self, playlist_id, playlist_config, videos):
		# Filter the video list for videos with matching tags
		matching = [
			video for video in videos.values()
			if all(tag in [t.lower() for t in video.tags] for tag in playlist_config.tags)
		]
		logging.debug(f"Found {len(matching)} matching videos for playlist {playlist_id}")

		# If we have nothing to add, short circuit without doing any API calls to save quota.
		playlist = self.get_playlist(playlist_id)
		matching_video_ids = {video.video_id for video in matching}
		playlist_video_ids = {entry.video_id for entry in playlist}
		new_videos = matching_video_ids - playlist_video_ids
		reorderings = self.find_playlist_reorderings(videos, playlist, playlist_config)
		if not (new_videos or reorderings):
			logging.debug("All videos already correctly ordered in playlist, nothing to do")
			return

		# Refresh our playlist state, if necessary.
		self.refresh_playlist(playlist_id)

		# Get an updated list of new videos
		playlist = self.get_playlist(playlist_id)
		matching_video_ids = {video.video_id for video in matching}
		playlist_video_ids = {entry.video_id for entry in self.get_playlist(playlist_id)}
		# It shouldn't matter, but just for clarity let's sort them by event order
		new_videos = sorted(matching_video_ids - playlist_video_ids, key=lambda v: v.start_time)

		# Perform any reorderings needed
		reorderings = self.find_playlist_reorderings(videos, playlist, playlist_config)
		for entry, index in reorderings:
			self.reorder_in_playlist(playlist_id, entry, index)

		# Insert each new video one at a time
		logging.debug(f"Inserting new videos for playlist {playlist_id}: {new_videos}")
		for video in new_videos:
			index = self.find_insert_index(videos, playlist_config, self.get_playlist(playlist_id), video)
			self.insert_into_playlist(playlist_id, video.video_id, index)


	def find_playlist_reorderings(self, videos, playlist, playlist_config):
		"""Looks through the playlist for videos that should be reordered.
		Returns a list of (entry, new index) to reorder.
		Right now this is only checked for the first and last videos as per playlist_config,
		all other misorderings are ignored."""
		result = []
		for index, entry in enumerate(playlist):
			if entry.video_id not in videos:
				# Unknown videos should always remain in-place.
				continue
			video = videos[video_id]

			if video.id == playlist.first_event_id:
				new_index = 0
			elif video.id == playlist.last_event_id:
				new_index = len(playlist) - 1
			else:
				continue

			if index != new_index:
				result.append((entry, new_index))
		return result

	def refresh_playlist(self, playlist_id):
		"""Check playlist mirror is in a good state, and fetch it if it isn't.
		We try to do this with only one page of list output, to save on quota.
		If the total length does not match (or we don't have a copy at all),
		then we do a full refresh.
		"""
		logging.debug(f"Fetching first page of playlist {playlist_id}")
		query = self.api.list_playlist(playlist_id)
		# See if we can avoid further page fetches.
		if playlist_id not in self.playlist_state:
			logging.info(f"Fetching playlist {playlist_id} because we don't currently have it")
		elif query.is_complete:
			logging.debug(f"First page of {playlist_id} was entire playlist")
		elif len(self.get_playlist(playlist_id)) == query.total_size:
			logging.debug(f"Skipping fetching of remainder of playlist {playlist_id}, size matches")
			return
		else:
			logging.warning("Playlist {} has size mismatch ({} saved vs {} actual), refetching".format(
				playlist_id, len(self.get_playlist(playlist_id)), query.total_size,
			))
		# Fetch remaining pages, if any
		query.fetch_all()
		# Update saved copy with video ids
		self.playlist_state[playlist_id] = [
			PlaylistEntry(
				item['id'],
				# api implies it's possible that non-videos are added, so videoId might not exist
				item['snippet']['resourceId'].get('videoId'),
			) for item in query.items
		]

	def find_insert_index(self, videos, playlist_config, playlist, new_video):
		"""Find the index at which to insert new_video into playlist such that
		playlist remains sorted (it is assumed to already be sorted).
		videos should be a mapping from video ids to video info.
		"""
		# Handle special cases first.
		if playlist_config.first_event_id == new_video.id:
			return 0
		if playlist_config.last_event_id == new_video.id:
			return len(playlist)

		# To try to behave as best we can in the presence of mis-sorted playlists,
		# we walk through the list linearly. We insert immediately before the first
		# item that should be after us in sort order.
		# Note that we treat unknown items (videos we don't know) as being before us
		# in sort order, so that we always insert after them.
		for n, (_, video_id) in enumerate(playlist):
			if video_id not in videos:
				# ignore unknowns
				continue
			video = videos[video_id]

			# The starting video of a playlist can have its own times, unaffiliated with other videos
			if video.id == playlist_config.first_event_id:
				continue
			# The new video needs to go before the last video in the playlist.
			# This will produce incorrect results if the last video is in the wrong position
			# so we only accept this if the last video is actually in the last position,
			# otherwise we ignore it.
			if video.id == playlist_config.last_event_id:
				if n == len(playlist) - 1:
					return n
				continue
			# if this video is after new video, return this index
			if new_video.start_time < video.start_time:
				return n
		# if we reach here, it means everything on the list was before the new video
		# therefore insert at end
		return len(playlist)

	def insert_into_playlist(self, playlist_id, video_id, index):
		"""Insert video into given playlist at given index.
		Makes the API call then also updates our mirrored copy.
		"""
		logging.info(f"Inserting {video_id} at index {index} of {playlist_id}")
		entry_id = self.api.insert_into_playlist(playlist_id, video_id, index)
		# Update our copy
		self.playlist_state.setdefault(playlist_id, []).insert(index, PlaylistEntry(entry_id, video_id)

	def reorder_in_playlist(self, playlist_id, entry, new_index):
		"""Take an existing entry in a given playlist and move it to the new index.
		Other entries are shifted to compensate (ie. forwards if the entry moved backwards,
		backwards if the entry moved forwards).
		"""
		playlist = self.get_playlist(playlist_id)
		assert entry in playlist, f"Tried to move entry {entry} which was not in our copy of {playlist_id}: {playlist}"

		logging.info(f"Moving {entry.video_id} (entry {entry.entry_id}) to new index {new_index})")
		try:
			self.api.update_playlist_entry(playlist_id, entry, new_index)
		except APIException as e:
			# 404 indicates the entry id no longer exists. Anything else, just raise.
			if e.code != 404:
				raise
			# We know our view of the playlist is wrong, so the safest thing to do is error out
			# and let higher-level code decide how to start again from the beginning.
			logging.warning(f"Playlist {playlist_id} no longer contains entry {entry.entry_id}, invalidating cache")
			self.reset(playlist_id)
			raise PlaylistOutdated()

		# Success, also update our local copy
		playlist.remove(entry)
		playlist.insert(new_index, entry)


class YoutubeAPI(object):
	def __init__(self, client):
		self.client = client
		# We've observed failures in the playlist API when doing concurrent calls for the same video.
		# We could maybe have a per-video lock but this is easier.
		self.insert_lock = gevent.lock.RLock()

	def insert_into_playlist(self, playlist_id, video_id, index):
		json = {
			"snippet": {
				"playlistId": playlist_id,
				"resourceId": {
					"kind": "youtube#video",
					"videoId": video_id,
				},
				"position": index,
			},
		}
		with self.insert_lock:
			resp = self.client.request("POST", "https://www.googleapis.com/youtube/v3/playlistItems",
				params={"part": "snippet"},
				json=json,
				metric_name="playlist_insert",
			)
		if not resp.ok:
			raise APIException("Failed to insert {video_id} at index {index} of {playlist} with {resp.status_code}: {resp.content}".format(
				playlist=playlist_id, video_id=video_id, index=index, resp=resp,
			), code=resp.status_code)
		# TODO return entry_id from resp

	def update_playlist_entry(self, playlist_id, entry, new_index):
		json = {
			"id": entry.entry_id,
			"snippet": {
				"playlistId": playlist_id,
				"resourceId": {
					"kind": "youtube#video",
					"videoId": entry.video_id,
				},
				"position": new_index,
			},
		}
		with self.insert_lock:
			resp = self.client.request("PUT", "https://www.googleapis.com/youtube/v3/playlistItems",
				params={"part": "snippet"},
				json=json,
				metric_name="playlist_update",
			)
		if not resp.ok:
			raise APIException(
				f"Failed to update {entry.entry_id} of {playlist_id} to {entry.video_id} at index {new_index} with {resp.status_code}: {resp.content}",
				code=resp.status_code,
			)

	def list_playlist(self, playlist_id):
		"""Fetches the first page of playlist contents and returns a ListQuery object.
		You can use this object to look up info and optionally retrieve the whole playlist."""
		data = self._list_playlist(playlist_id)
		return ListQuery(self, playlist_id, data)

	def _list_playlist(self, playlist_id, page_token=None):
		"""Internal method that actually does the list query.
		Returns the full response json."""
		params = {
			"part": "snippet",
			"playlistId": playlist_id,
			"maxResults": 50,
		}
		if page_token is not None:
			params['pageToken'] = page_token
		resp = self.client.request("GET", "https://www.googleapis.com/youtube/v3/playlistItems",
			params=params,
			metric_name="playlist_list",
		)
		if not resp.ok:
			raise APIException("Failed to list {playlist} (page_token={page_token!r}) with {resp.status_code}: {resp.content}".format(
				playlist=playlist_id, page_token=page_token, resp=resp,
			), code=resp.status_code)
		return resp.json()


class ListQuery(object):
	"""Represents a partially-fetched list query for all playlist items.
	To save on quota, we avoid fetching the entire playlist until asked."""
	def __init__(self, api, playlist_id, data):
		self.api = api
		self.playlist_id = playlist_id
		self.total_size = data['pageInfo']['totalResults']
		self.is_complete = self.total_size <= data['pageInfo']['resultsPerPage']
		self.items = data['items']
		self.page_token = data.get('nextPageToken')

	def fetch_all(self):
		if self.is_complete:
			return
		page_token = self.page_token
		while len(self.items) < self.total_size:
			assert page_token is not None, "More items to fetch but no page token"
			data = self.api._list_playlist(self.playlist_id, page_token)
			self.items += data['items']
			page_token = data.get('nextPageToken')
			# I'm just being paranoid here about an infinite loop blowing our quota,
			# let's assert we always are making forward progress
			assert data['items'], "Got no extra items from new page"
		self.is_complete = True


def parse_playlist_arg(arg):
	playlist, tags = arg.split('=', 1)
	tags = tags.split(",") if tags else []
	tags = [tag.lower() for tag in tags]
	return playlist, tags


@argh.arg("playlists", nargs="*", metavar="PLAYLIST={TAG,}", type=parse_playlist_arg, help=
	"Each playlist arg specifies a youtube playlist ID, along with any number of tags. "
	"Events will be added to the playlist if that event has all the tags. For example, "
	"some_playlist_id=Day 1,Technical would populate that playlist with all Technical events "
	"from Day 1. Note that having no tags (ie. 'id=') is allowed and all events will be added to it. "
	"Note playlist ids must be unique (can't specify the same one twice). "
	"These playlists will be added to ones listed in the database."
)
def main(
	dbconnect,
	creds_file,
	playlists,
	upload_location_allowlist="youtube",
	interval=600,
	metrics_port=8007,
	backdoor_port=0,
):
	"""
	dbconnect should be a postgres connection string

	creds_file should contain youtube api creds

	upload_location_allowlist is a comma-seperated list of database upload locations to
	consider as eligible to being added to playlists. For these locations, the database video id
	must be a youtube video id.
	Note that non-public videos will never be added to playlists, even if they have a matching
	upload_location.

	interval is how often to check for new videos, default every 10min.
	"""
	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	upload_locations = upload_location_allowlist.split(",") if upload_location_allowlist else []
	playlists = dict(playlists)

	stop = gevent.event.Event()
	gevent.signal_handler(signal.SIGTERM, stop.set) # shut down on sigterm

	logging.info("Starting up")

	with open(creds_file) as f:
		creds = json.load(f)
	client = GoogleAPIClient(creds['client_id'], creds['client_secret'], creds['refresh_token'])

	dbmanager = DBManager(dsn=dbconnect)
	manager = PlaylistManager(dbmanager, client, upload_locations, playlists)

	while not stop.is_set():
		try:
			manager.run_once()
		except Exception:
			logging.exception("Failed to run playlist manager")
			manager.reset()
		stop.wait(interval) # wait for interval, or until stopping

	logging.info("Stopped")
