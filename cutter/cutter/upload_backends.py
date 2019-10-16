
import logging

from common.googleapis import GoogleAPIClient


class UploadBackend(object):
	"""Represents a place a video can be uploaded,
	and maintains any state needed to perform uploads.

	Config args for the backend are passed into __init__ as kwargs,
	along with credentials as the first arg.

	Should have a method upload_video(title, description, tags, data).
	Title, description and tags may have backend-specific meaning.
	Tags is a list of string.
	Data may be a string, file-like object or iterator of strings.
	It should return (video_id, video_link).

	If the video must undergo additional processing before it's available
	(ie. it should go into the TRANSCODING state), then the backend should
	define the 'needs_transcode' attribute as True.
	If it does, it should also have a method check_status(ids) which takes a
	list of video ids and returns a list of the ones who have finished processing.

	The upload backend also determines the encoding settings for the cutting
	process, this is given as a list of ffmpeg args
	under the 'encoding_settings' attribute.
	"""

	needs_transcode = False

	# reasonable default if settings don't otherwise matter
	encoding_settings = [] # TODO

	def upload_video(self, title, description, tags, data):
		raise NotImplementedError

	def check_status(self, ids):
		raise NotImplementedError


class Youtube(UploadBackend):
	"""Represents a youtube channel to upload to, and settings for doing so.
	Config args besides credentials:
		hidden:
			If false, video is public. If true, video is unlisted. Default false.
	"""

	needs_transcode = True
	encoding_settings = [] # TODO youtube's recommended settings

	def __init__(self, credentials, hidden=False):
		self.logger = logging.getLogger(type(self).__name__)
		self.client = GoogleAPIClient(
			credentials['client_id'],
			credentials['client_secret'],
			credentials['refresh_token'],
		)
		self.hidden = hidden

	def upload_video(self, title, description, tags, data):
		json = {
			'snippet': {
				'title': title,
				'description': description,
				'tags': tags,
			},
		}
		if self.hidden:
			json['status'] = {
				'privacyStatus': 'unlisted',
			}
		resp = self.client.request('POST',
			'https://www.googleapis.com/upload/youtube/v3/videos',
			params={
				'part': 'snippet,status' if self.hidden else 'snippet',
				'uploadType': 'resumable',
			},
			json=json,
		)
		resp.raise_for_status()
		upload_url = resp.headers['Location']
		resp = self.client.request('POST', upload_url, data=data)
		resp.raise_for_status()
		id = resp.json()['id']
		return id, 'https://youtu.be/{}'.format(id)

	def check_status(self, ids):
		output = []
		# Break up into groups of 10 videos. I'm not sure what the limit is so this is reasonable.
		for i in range(0, len(ids), 10):
			group = ids[i:i+10]
			resp = self.client.request('GET',
				'https://www.googleapis.com/youtube/v3/videos',
				params={
					'part': 'id,status',
					'id': ','.join(group),
				},
			)
			resp.raise_for_status()
			for item in resp.json()['items']:
				if item['status']['uploadStatus'] == 'processed':
					output.append(item['id'])
		return output
