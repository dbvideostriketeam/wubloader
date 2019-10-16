
import errno
import logging
import os
import re
import uuid

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


class Local(UploadBackend):
	"""An "upload" backend that just saves the file to local disk.
	Needs no credentials. Config args:
		path:
			Where to save the file.
		url_prefix:
			The leading part of the URL to return.
			The filename will be appended to this to form the full URL.
			So for example, if you set "http://example.com/videos/",
			then a returned video URL might look like:
				"http://example.com/videos/my-example-video-1ffd816b-6496-45d4-b8f5-5eb06ee532f9.ts"
			If not given, returns a file:// url with the full path.
	Saves files under their title, plus a random video id to avoid conflicts.
	Ignores description and tags.
	"""

	def __init__(self, credentials, path, url_prefix=None):
		self.path = path
		self.url_prefix = url_prefix
		# make path if it doesn't already exist
		try:
			os.makedirs(self.path)
		except OSError as e:
			if e.errno != errno.EEXIST:
				raise
			# ignore already-exists errors

	def upload_video(self, title, description, tags, data):
		video_id = uuid.uuid4()
		# make title safe by removing offending characters, replacing with '-'
		title = re.sub('[^A-Za-z0-9_]', '-', title)
		filename = '{}-{}.ts'.format(title, video_id) # TODO with re-encoding, this ext must change
		filepath = os.path.join(self.path, filename)
		with open(filepath, 'w') as f:
			if isinstance(data, str):
				# string
				f.write(data)
			elif hasattr(data, 'read'):
				# file-like object
				CHUNK_SIZE = 16*1024
				chunk = data.read(CHUNK_SIZE)
				while chunk:
					f.write(chunk)
					chunk = data.read(CHUNK_SIZE)
			else:
				# iterable of string
				for chunk in data:
					f.write(chunk)
		if self.url_prefix is not None:
			url = self.url_prefix + filename
		else:
			url = 'file://{}'.format(filepath)
		return video_id, url
