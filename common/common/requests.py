
"""Code for instrumenting requests calls. Requires requests, obviously."""

import urlparse

import requests
import prometheus_client as prom
from monotonic import monotonic

request_latency = prom.Histogram(
	'http_client_request_latency',
	'Time taken to make an outgoing HTTP request. '
	'Status = "error" is used if an error occurs. Measured as time from first byte sent to '
	'headers finished being parsed, ie. does not include reading a streaming response.',
	['name', 'method', 'domain', 'status'],
)

response_size = prom.Histogram(
	'http_client_response_size',
	"The content length of (non-streaming) responses to outgoing HTTP requests.",
	['name', 'method', 'domain', 'status'],
)

request_concurrency = prom.Gauge(
	'http_client_request_concurrency',
	"The number of outgoing HTTP requests currently ongoing",
	['name', 'method', 'domain'],
)

class InstrumentedSession(requests.Session):
	"""A requests Session that automatically records metrics on requests made.
	Users may optionally pass a 'metric_name' kwarg that will be included as the 'name' label.
	"""

	def request(self, method, url, *args, **kwargs):
		_, domain, _, _, _ = urlparse.urlsplit(url)
		name = kwargs.pop('metric_name', '')

		start = monotonic() # we only use our own measured latency if an error occurs
		try:
			with request_concurrency.labels(name, method, domain).track_inprogress():
				response = super(InstrumentedSession, self).request(method, url, *args, **kwargs)
		except Exception:
			latency = monotonic() - start
			request_latency.labels(name, method, domain, "error").observe(latency)
			raise

		request_latency.labels(name, method, domain, response.status_code).observe(response.elapsed)
		if 'content-length' in response.headers:
			response_size.labels(name, method, domain, response.status_code).observe(response.headers['content-length'])
		return response
