
import errno
import json
import logging
import os
import re
import time
import uuid

import common
from common.googleapis import GoogleAPIClient


class UploadError(Exception):
	"""Upload backends should raise this error when uploading
	and an expected failure occurs.
	In particular, they should NOT raise this error if they're
	unsure whether the video was uploaded or not.
	They should also indicate if the error is retryable without
	manual intervention.
	Examples of retryable errors:
		Short-term rate limits (try again in a few seconds)
		Upload backends which are fully idempotent
	Examples of unretryable errors:
		Bad Request (indicates logic bug, or that the video is unacceptable in some way)
		Long-term rate limits (trying again quickly is counterproductive, wait for operator)
	Examples of errors which should not be caught, allowing the FINALIZING logic
	to determine if it's safe to retry:
		500s (We don't know if the request went through)
		Network errors (same as above)
		Unexpected exceptions (they might have occurred after the upload is finished)

	Raisers should log the underlying exception before raising, as this error
	will not be further logged.
	"""
	def __init__(self, error, retryable=False):
		"""Error should be a string error message to put into the database."""
		self.error = error
		self.retryable = retryable

	def __str__(self):
		return "{} error while uploading: {}".format(
			"Retryable" if self.retryable else "Non-retryable",
			self.error,
		)


class UploadBackend(object):
	"""Represents a place a video can be uploaded,
	and maintains any state needed to perform uploads.

	Config args for the backend are passed into __init__ as kwargs,
	along with credentials as the first arg.

	Should have a method upload_video(title, description, tags, public, data).
	Title, description, tags and public may have backend-specific meaning.
	Tags is a list of string.
	Public is a boolean.
	Data is an iterator of bytes.
	It should return (video_id, video_link).

	If the video must undergo additional processing before it's available
	(ie. it should go into the TRANSCODING state), then the backend should
	define the 'needs_transcode' attribute as True.
	If it does, it should also have a method check_status(ids) which takes a
	list of video ids and returns a list of the ones who have finished processing.

	If updating existing videos is supported, the backend should also define a method
	update_video(video_id, title, description, tags, public).
	Fields which cannot be updated may be ignored.
	Must not change the video id or link. Returns nothing.

	If uploading thumbnails for a video is supported, the backend should define a method
	set_thumbnail(video_id, thumbnail) where thumbnail is a bytestring containing image data.
	Returns nothing.

	The upload backend also determines the encoding settings for the cutting
	process, this is given as a list of ffmpeg args
	under the 'encoding_settings' attribute.
	If this is not a list but the string "fast", instead uses the 'fast cut' strategy where nothing
	is transcoded.
	Similarly, the string "smart" uses the 'smart cut' strategy which is a fast cut with an additional
	pass to prevent timestamp issues.

	In addition, if the output format doesn't need a seekable file,
	you should set encoding_streamable = True so we know we can stream the output directly.
	"""

	needs_transcode = False

	# reasonable default if settings don't otherwise matter:
	# high-quality mpegts, without wasting too much cpu on encoding
	encoding_settings = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', '-f', 'mpegts']
	encoding_streamable = True

	def upload_video(self, title, description, tags, public, data):
		raise NotImplementedError

	def check_status(self, ids):
		raise NotImplementedError

	def update_video(self, video_id, title, description, tags, public):
		raise NotImplementedError

	def set_thumbnail(self, video_id, thumbnail):
		raise NotImplementedError


class Youtube(UploadBackend):
	"""Represents a youtube channel to upload to, and settings for doing so.
	Config args besides credentials:
		category_id:
			The numeric category id to set as the youtube category of all videos.
			Default is 23, which is the id for "Comedy". Set to null to not set.
		language:
			The language code to describe all videos as.
			Default is "en", ie. English. Set to null to not set.
		use_yt_recommended_encoding:
			Default False. If True, use the ffmpeg settings that Youtube recommends for
			fast processing once uploaded. We suggest not bothering, as it doesn't appear
			to make much difference.
		mime_type: You must set this to the correct mime type for the encoded video.
			Default is video/MP2T, suitable for fast cuts or -f mpegts.
	"""

	needs_transcode = True
	recommended_settings = [
		# Youtube's recommended settings:
		'-codec:v', 'libx264', # Make the video codec x264
		'-crf', '21', # Set the video quality, this produces the bitrate range that YT likes
		'-bf', '2', # Have 2 consecutive bframes, as requested
		'-flags', '+cgop', # Use closed GOP, as requested
		'-pix_fmt', 'yuv420p', # chroma subsampling 4:2:0, as requrested
		'-codec:a', 'aac', '-strict', '-2', # audio codec aac, as requested
		'-b:a', '384k' # audio bitrate at 348k for 2 channel, use 512k if 5.1 audio
		'-r:a', '48000', # set audio sample rate at 48000Hz, as requested
		'-movflags', 'faststart', # put MOOV atom at the front of the file, as requested
	]

	def __init__(self, credentials, category_id=23, language="en", use_yt_recommended_encoding=False,
		mime_type='video/MP2T'):
		self.logger = logging.getLogger(type(self).__name__)
		self.client = GoogleAPIClient(
			credentials['client_id'],
			credentials['client_secret'],
			credentials['refresh_token'],
		)
		self.category_id = category_id
		self.language = language
		self.mime_type = mime_type
		if use_yt_recommended_encoding:
			self.encoding_settings = self.recommended_settings
			self.encoding_streamable = False

	def upload_video(self, title, description, tags, public, data):
		json = {
			'snippet': {
				'title': title,
				'description': description,
				'tags': tags,
			},
			'status': {
				'privacyStatus': 'public' if public else 'unlisted',
			},
		}
		if self.category_id is not None:
			json['snippet']['categoryId'] = self.category_id
		if self.language is not None:
			json['snippet']['defaultLanguage'] = self.language
			json['snippet']['defaultAudioLanguage'] = self.language
		resp = self.client.request('POST',
			'https://www.googleapis.com/upload/youtube/v3/videos',
			headers={'X-Upload-Content-Type': self.mime_type},
			params={
				'part': 'snippet,status',
				'uploadType': 'resumable',
			},
			json=json,
			metric_name='create_video',
		)
		if not resp.ok:
			# Don't retry, because failed calls still count against our upload quota.
			# The risk of repeated failed attempts blowing through our quota is too high.
			raise UploadError("Youtube create video call failed with {resp.status_code}: {resp.content}".format(resp=resp))
		upload_url = resp.headers['Location']
		resp = self.client.request(
			'POST', upload_url,
			data=data,
			metric_name='upload_video',
		)
		if 400 <= resp.status_code < 500:
			# As above, don't retry. But with 4xx's we know the upload didn't go through.
			# On a 5xx, we can't be sure (the server is in an unspecified state).
			raise UploadError("Youtube video data upload failed with {resp.status_code}: {resp.content}".format(resp=resp))
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
				metric_name='list_videos',
			)
			resp.raise_for_status()
			for item in resp.json()['items']:
				if item['status']['uploadStatus'] == 'processed':
					output.append(item['id'])
		return output

	def update_video(self, video_id, title, description, tags, public):
		# Any values we don't give will be deleted on PUT, so we need to first
		# get all the existing values then merge in our updates.
		resp = self.client.request('GET',
			'https://www.googleapis.com/youtube/v3/videos',
			params={
				'part': 'id,snippet,status',
				'id': video_id,
			},
			metric_name='get_video',
		)
		resp.raise_for_status()
		data = resp.json()['items']
		if len(data) == 0:
			raise Exception("Could not find video {}".format(video_id))
		assert len(data) == 1
		data = data[0]
		snippet = data['snippet'].copy()
		status = data['status'].copy()

		snippet['title'] = title
		snippet['description'] = description
		snippet['tags'] = tags
		status['privacyStatus'] = 'public' if public else 'unlisted'
		# Since we're fetching this data anyway, we can save some quota by avoiding repeated work.
		# We could still race and do the same update twice, but that's fine.
		if snippet == data['snippet'] and status == data['status']:
			self.logger.info("Skipping update for video {}: No changes".format(video_id))
			return

		resp = self.client.request('PUT',
			'https://www.googleapis.com/youtube/v3/videos',
			params={
				'part': 'id,snippet,status',
			},
			json={
				'id': video_id,
				'snippet': snippet,
				'status': status,
			},
			metric_name='update_video',
		)
		if resp.status_code == 409:
			raise UploadError("Multiple updates to same video, got 409: {}".format(resp.text), retryable=True)
		resp.raise_for_status()

	def set_thumbnail(self, video_id, thumbnail):
		resp = self.client.request('POST',
			'https://www.googleapis.com/upload/youtube/v3/thumbnails/set',
			params={'videoId': video_id},
			headers={'Content-Type': 'image/png'},
			data=thumbnail,
		)
		resp.raise_for_status()


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
		write_info:
			If true, writes a json file alongside the video file containing
			the video title, description, tags and public setting.
			This is intended primarily for testing purposes.
	Saves files under their title, plus a random video id to avoid conflicts.
	Ignores other parameters.
	"""

	def __init__(self, credentials, path, url_prefix=None, write_info=False):
		self.path = path
		self.url_prefix = url_prefix
		self.write_info = write_info
		# make path if it doesn't already exist
		try:
			os.makedirs(self.path)
		except OSError as e:
			if e.errno != errno.EEXIST:
				raise
			# ignore already-exists errors

	def upload_video(self, title, description, tags, public, data):
		video_id = str(uuid.uuid4())
		# make title safe by removing offending characters, replacing with '-'
		safe_title = re.sub('[^A-Za-z0-9_]', '-', title)
		ext = 'ts'
		filename = '{}-{}.{}'.format(safe_title, video_id, ext)
		filepath = os.path.join(self.path, filename)
		try:
			if self.write_info:
				with open(os.path.join(self.path, '{}-{}.json'.format(safe_title, video_id)), 'w') as f:
					common.writeall(f.write, json.dumps({
						'title': title,
						'description': description,
						'tags': tags,
						'public': public,
					}) + '\n')
			with open(filepath, 'wb') as f:
				for chunk in data:
					common.writeall(f.write, chunk)
		except (OSError, IOError) as e:
			# Because duplicate videos don't actually matter with this backend,
			# we consider all disk errors retryable.
			raise UploadError("{} while writing local file: {}".format(type(e).__name__, e), retryable=True)
		if self.url_prefix is not None:
			url = self.url_prefix + filename
		else:
			url = 'file://{}'.format(filepath)
		return video_id, url

	def update_video(self, video_id, title, description, tags, public):
		if not self.write_info:
			return
		safe_title = re.sub('[^A-Za-z0-9_]', '-', title)
		with open(os.path.join(self.path, '{}-{}.json'.format(safe_title, video_id)), 'w') as f:
			common.writeall(f.write, json.dumps({
				'title': title,
				'description': description,
				'tags': tags,
				'public': public,
			}) + '\n')

	def set_thumbnail(self, video_id, thumbnail):
		filepath = os.path.join(self.path, "{}.png".format(video_id))
		common.atomic_write(filepath, thumbnail)


class LocalArchive(Local):
	"""Similar to Local() but does archive cuts. See archive_cut_segments()."""
	encoding_settings = "archive"

	def upload_video(self, title, description, tags, public, data):
		tempfiles = data
		# make title safe by removing offending characters, replacing with '-'
		safe_title = re.sub('[^A-Za-z0-9_]', '-', title)
		# To aid in finding the "latest" version if re-edited, prefix with current time.
		prefix = str(time.time())
		video_dir = "{}-{}".format(prefix, safe_title)
		common.ensure_directory(os.path.join(self.path, video_dir))
		for n, tempfile in enumerate(tempfiles):
			filepath = os.path.join(self.path, video_dir, "{}-{}.mkv".format(safe_title, n))
			common.ensure_directory(filepath)
			# We're assuming these are on the same filesystem. This may not always be true
			# but it will be in our normal setup. If we ever need this in the future, we'll fix it then.
			os.rename(tempfile, filepath)
		if self.url_prefix is not None:
			url = self.url_prefix + video_dir
		else:
			url = "file://{}".format(video_dir)
		return prefix, url
