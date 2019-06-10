
import logging
import time

import gevent
import requests


class Youtube(object):
	"""Manages access to youtube and maintains an active access token"""

	ACCESS_TOKEN_ERROR_RETRY_INTERVAL = 10
	# Refresh token 10min before it expires (it normally lasts an hour)
	ACCESS_TOKEN_REFRESH_TIME_BEFORE_EXPIRY = 600

	def __init__(self, client_id, client_secret, refresh_token):
		self.logger = logging.getLogger(type(self).__name__)
		self.client_id = client_id
		self.client_secret = client_secret
		self.refresh_token = refresh_token

		self._first_get_access_token = gevent.spawn(self.get_access_token)

	@property
	def access_token(self):
		"""Blocks if access token unavailable yet"""
		self._first_get_access_token.join()
		return self._access_token

	def get_access_token(self):
		"""Authenticates against the youtube API and retrieves a token we will use in
		subsequent requests.
		This function gets called automatically when needed, there should be no need to call it
		yourself."""
		while True:
			try:
				start_time = time.time()
				resp = requests.post('https://www.googleapis.com/oauth2/v4/token', data={
					'client_id': self.client_id,
					'client_secret': self.client_secret,
					'refresh_token': self.refresh_token,
					'grant_type': 'refresh_token',
				})
				resp.raise_for_status()
				data = resp.json()
				self._access_token = data['access_token']
				expires_in = (start_time + data['expires_in']) - time.time()
				if expires_in < self.ACCESS_TOKEN_REFRESH_TIME_BEFORE_EXPIRY:
					self.logger.warning("Access token expires in {}s, less than normal leeway time of {}s".format(
						expires_in, self.ACCESS_TOKEN_REFRESH_TIME_BEFORE_EXPIRY,
					))
				gevent.spawn_later(expires_in - self.ACCESS_TOKEN_REFRESH_TIME_BEFORE_EXPIRY, self.get_access_token)
			except Exception:
				self.logger.exception("Failed to fetch access token, retrying")
				self.wait(self.ACCESS_TOKEN_ERROR_RETRY_INTERVAL)
			else:
				break

	def auth_headers(self):
		return {'Authorization': 'Bearer {}'.format(self.access_token)}

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
		resp = requests.post(
			'https://www.googleapis.com/upload/youtube/v3/videos',
			headers=self.auth_headers(),
			params={
				'part': 'snippet,status' if hidden else 'snippet',
				'uploadType': 'resumable',
			},
			json=json,
		)
		resp.raise_for_status()
		upload_url = resp.headers['Location']
		resp = requests.post(upload_url, headers=self.auth_headers(), data=data)
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
			resp = requests.get(
				'https://www.googleapis.com/youtube/v3/videos',
				headers=self.auth_headers(),
				params={
					'part': 'id,status',
					'id': ','.join(group),
				},
			)
			resp.raise_for_status()
			for item in resp.json()['items']:
				output[item['id']] = item['status']['uploadStatus']
		return output
