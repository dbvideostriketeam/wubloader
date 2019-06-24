
import logging

from common.googleapis import GoogleAPIClient


class Youtube(object):
	"""Manages youtube API operations"""

	def __init__(self, client_id, client_secret, refresh_token):
		self.logger = logging.getLogger(type(self).__name__)
		self.client = GoogleAPIClient(client_id, client_secret, refresh_token)

	def upload_video(self, title, description, tags, data, hidden=False):
		"""Data may be a string, file-like object or iterator. Returns id."""
		json = {
			'snippet': {
				'title': title,
				'description': description,
				'tags': tags,
			},
		}
		if hidden:
			json['status'] = {
				'privacyStatus': 'unlisted',
			}
		resp = self.client.request('POST',
			'https://www.googleapis.com/upload/youtube/v3/videos',
			params={
				'part': 'snippet,status' if hidden else 'snippet',
				'uploadType': 'resumable',
			},
			json=json,
		)
		resp.raise_for_status()
		upload_url = resp.headers['Location']
		resp = self.client.request('POST', upload_url, data=data)
		resp.raise_for_status()
		return resp.json()['id']

	def get_video_status(self, ids):
		"""For a list of video ids, returns a dict {id: upload status}.
		A video is fully processed when upload status is 'processed'.
		NOTE: Video ids may be missing from the result, this probably indicates
		the video is errored.
		"""
		output = {}
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
				output[item['id']] = item['status']['uploadStatus']
		return output
