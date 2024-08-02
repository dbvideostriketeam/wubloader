
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


class PlaylistManager(object):

	def __init__(self, dbmanager, api_client, upload_locations, playlist_tags):
		self.dbmanager = dbmanager
		self.api = YoutubeAPI(api_client)
		self.upload_locations = upload_locations
		self.static_playlist_tags = playlist_tags
		self.reset()

	def reset(self, playlist=None):
		"""Called to clear saved state and force a refresh after errors.
		Either reset a specific playlist, or all if no arg given.
		"""
		if playlist is None:
			# playlist_state represents our mirrored view of the list of items in each playlist.
			# If a playlist is not present, it means we need to refresh our view of it.
			# {playlist_id: [video_id]}
			self.playlist_state = {}
		else:
			self.playlist_state.pop(playlist, None)

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
		logging.debug("Found {} eligible videos".format(len(videos)))

		logging.info("Getting dynamic playlists")
		playlist_tags = self.get_playlist_tags()
		logging.debug("Found {} playlists".format(len(playlist_tags)))

		# start all workers
		workers = {}
		for playlist, tags in playlist_tags.items():
			workers[playlist] = gevent.spawn(self.update_playlist, playlist, tags, videos)

		# check each one for success, reset on failure
		for playlist, worker in workers.items():
			try:
				worker.get()
			except Exception:
				logging.exception("Failed to update playlist {}".format(playlist))
				self.reset(playlist)

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

	def get_playlist_tags(self):
		conn = self.dbmanager.get_conn()
		playlist_tags = {
			row.playlist_id: [tag.lower() for tag in row.tags]
			for row in query(conn, "SELECT playlist_id, tags FROM playlists")
		}
		self.dbmanager.put_conn(conn)
		duplicates = set(playlist_tags) & set(self.static_playlist_tags)
		if duplicates:
			raise ValueError("Some playlists are listed in both static and dynamic playlist sources: {}".format(", ".join(duplicates)))
		playlist_tags.update(self.static_playlist_tags)
		return playlist_tags

	def update_playlist(self, playlist, tags, videos):
		# Filter the video list for videos with matching tags
		matching = [
			video for video in videos.values()
			if all(tag in [t.lower() for t in video.tags] for tag in tags)
		]
		logging.debug("Found {} matching videos for playlist {}".format(len(matching), playlist))
		# If we have nothing to add, short circuit without doing any API calls to save quota.
		if not set([v.video_id for v in matching]) - set(self.playlist_state.get(playlist, [])):
			logging.debug("All videos already in playlist, nothing to do")
			return
		# Refresh our playlist state, if necessary.
		self.refresh_playlist(playlist)
		# Get an updated list of new videos
		new_videos = [
			video for video in matching
			if video.video_id not in self.playlist_state[playlist]
		]
		# It shouldn't matter, but just for clarity let's sort them by event order
		new_videos.sort(key=lambda v: v.start_time)
		# Insert each new video one at a time
		logging.debug("Inserting new videos for playlist {}: {}".format(playlist, new_videos))
		for video in new_videos:
			index = self.find_insert_index(videos, self.playlist_state[playlist], video)
			self.insert_into_playlist(playlist, video.video_id, index)

	def refresh_playlist(self, playlist):
		"""Check playlist mirror is in a good state, and fetch it if it isn't.
		We try to do this with only one page of list output, to save on quota.
		If the total length does not match (or we don't have a copy at all),
		then we do a full refresh.
		"""
		logging.debug("Fetching first page of playlist {}".format(playlist))
		query = self.api.list_playlist(playlist)
		# See if we can avoid further page fetches.
		if playlist not in self.playlist_state:
			logging.info("Fetching playlist {} because we don't currently have it".format(playlist))
		elif query.is_complete:
			logging.debug("First page of {} was entire playlist".format(playlist))
		elif len(self.playlist_state[playlist]) == query.total_size:
			logging.debug("Skipping fetching of remainder of playlist {}, size matches".format(playlist))
			return
		else:
			logging.warning("Playlist {} has size mismatch ({} saved vs {} actual), refetching".format(
				playlist, len(self.playlist_state[playlist]), query.total_size,
			))
		# Fetch remaining pages, if any
		query.fetch_all()
		# Update saved copy with video ids
		self.playlist_state[playlist] = [
			item['snippet']['resourceId'].get('videoId') # api implies it's possible that non-videos are added
			for item in query.items
		]

	def find_insert_index(self, videos, playlist, new_video):
		"""Find the index at which to insert new_video into playlist such that
		playlist remains sorted (it is assumed to already be sorted).
		videos should be a mapping from video ids to video info.
		"""
		# To try to behave as best we can in the presence of mis-sorted playlists,
		# we walk through the list linearly. We insert immediately before the first
		# item that should be after us in sort order.
		# Note that we treat unknown items (videos we don't know) as being before us
		# in sort order, so that we always insert after them.
		for n, video_id in enumerate(playlist):
			if video_id not in videos:
				# ignore unknowns
				continue
			video = videos[video_id]
			# if this video is after new video, return this index
			if new_video.start_time < video.start_time:
				return n
		# if we reach here, it means everything on the list was before the new video
		# therefore insert at end
		return len(playlist)

	def insert_into_playlist(self, playlist, video_id, index):
		"""Insert video into given playlist at given index.
		Makes the API call then also updates our mirrored copy.
		"""
		logging.info("Inserting {} at index {} of {}".format(video_id, index, playlist))
		self.api.insert_into_playlist(playlist, video_id, index)
		# Update our copy
		self.playlist_state.setdefault(playlist, []).insert(index, video_id)


class YoutubeAPI(object):
	def __init__(self, client):
		self.client = client
		# We've observed failures in the playlist API when doing concurrent calls for the same video.
		# We could maybe have a per-video lock but this is easier.
		self.insert_lock = gevent.lock.RLock()

	def insert_into_playlist(self, playlist, video_id, index):
		json = {
			"snippet": {
				"playlistId": playlist,
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
				raise Exception("Failed to insert {video_id} at index {index} of {playlist} with {resp.status_code}: {resp.content}".format(
					playlist=playlist, video_id=video_id, index=index, resp=resp,
				))

	def list_playlist(self, playlist):
		"""Fetches the first page of playlist contents and returns a ListQuery object.
		You can use this object to look up info and optionally retrieve the whole playlist."""
		data = self._list_playlist(playlist)
		return ListQuery(self, playlist, data)

	def _list_playlist(self, playlist, page_token=None):
		"""Internal method that actually does the list query.
		Returns the full response json."""
		params = {
			"part": "snippet",
			"playlistId": playlist,
			"maxResults": 50,
		}
		if page_token is not None:
			params['pageToken'] = page_token
		resp = self.client.request("GET", "https://www.googleapis.com/youtube/v3/playlistItems",
			params=params,
			metric_name="playlist_list",
		)
		if not resp.ok:
			raise Exception("Failed to list {playlist} (page_token={page_token!r}) with {resp.status_code}: {resp.content}".format(
				playlist=playlist, page_token=page_token, resp=resp,
			))
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
