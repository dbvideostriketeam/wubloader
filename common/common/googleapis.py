
import time
import logging

import gevent

from .requests import InstrumentedSession

# Wraps all requests in some metric collection
requests = InstrumentedSession()


class GoogleAPIClient(object):
	"""Manages access to google apis and maintains an active access token.
	Make calls using client.request(), which is a wrapper for requests.request().
	"""

	ACCESS_TOKEN_ERROR_RETRY_INTERVAL = 10
	# Refresh token 10min before it expires (it normally lasts an hour)
	ACCESS_TOKEN_REFRESH_TIME_BEFORE_EXPIRY = 600

	def __init__(self, client_id, client_secret, refresh_token):
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
		"""Authenticates against google's API and retrieves a token we will use in
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
				}, metric_name='get_access_token')
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
				logging.exception("Failed to fetch access token, retrying")
				self.wait(self.ACCESS_TOKEN_ERROR_RETRY_INTERVAL)
			else:
				break

	def request(self, method, url, headers={}, **kwargs):
		# merge in auth header
		headers = dict(headers, Authorization='Bearer {}'.format(self.access_token))
		return requests.request(method, url, headers=headers, **kwargs)
