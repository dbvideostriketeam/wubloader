"""
Code shared between components to gather stats from flask methods.
Note that this code requires flask, but the common module as a whole does not
to avoid needing to install them for components that don't need it.
"""

import functools

from flask import request
from flask import g as request_store
from monotonic import monotonic
import prometheus_client as prom


# Generic metrics that all http requests get logged to (see below for specific metrics per endpoint)

LATENCY_HELP = "Time taken to run the request handler and create a response"
# buckets: very long playlists / cutting can be quite slow,
# so we have a wider range of latencies than default, up to 10min.
LATENCY_BUCKETS = [.001, .005, .01, .05, .1, .5, 1, 5, 10, 30, 60, 120, 300, 600]
generic_latency = prom.Histogram(
	'http_request_latency_all', LATENCY_HELP,
	['endpoint', 'method', 'status'],
	buckets=LATENCY_BUCKETS,
)

SIZE_HELP = 'Size in bytes of response body for non-chunked responses'
# buckets: powers of 4 up to 1GiB (1, 4, 16, 64, 256, 1Ki, 4Ki, ...)
SIZE_BUCKETS = [4**i for i in range(16)]
generic_size = prom.Histogram(
	'http_response_size_all', SIZE_HELP,
	['endpoint', 'method', 'status'],
	buckets=SIZE_BUCKETS,
)

CONCURRENT_HELP = 'Number of requests currently ongoing'
generic_concurrent = prom.Gauge(
	'http_request_concurrency_all', CONCURRENT_HELP,
	['endpoint', 'method'],
)


def request_stats(fn):
	"""Decorator that wraps a handler func to collect metrics.
	Adds handler func args as labels, along with 'endpoint' label using func's name,
	method and response status where applicable."""
	# We have to jump through some hoops here, because the prometheus client lib demands
	# we pre-define our label names, but we don't know the names of the handler kwargs
	# until the first time the function's called. So we delay defining the metrics until
	# first call.
	# In addition, it doesn't let us have different sets of labels with the same name.
	# So we record everything twice: Once under a generic name with only endpoint, method
	# and status, and once under a name specific to the endpoint with the full set of labels.
	metrics = {}
	endpoint = fn.__name__

	@functools.wraps(fn)
	def _stats(**kwargs):
		if not metrics:
			# first call, set up metrics
			labels_no_status = sorted(kwargs.keys()) + ['endpoint', 'method']
			labels = labels_no_status + ['status']
			metrics['latency'] = prom.Histogram(
				'http_request_latency_{}'.format(endpoint), LATENCY_HELP,
				labels, buckets=LATENCY_BUCKETS,
			)
			metrics['size'] = prom.Histogram(
				'http_response_size_{}'.format(endpoint), SIZE_HELP,
				labels, buckets=SIZE_BUCKETS,
			)
			metrics['concurrent'] = prom.Gauge(
				'http_request_concurrency_{}'.format(endpoint), CONCURRENT_HELP,
				labels_no_status,
			)

		request_store.metrics = metrics
		request_store.endpoint = endpoint
		request_store.method = request.method
		request_store.labels = {k: str(v) for k, v in kwargs.items()}
		generic_concurrent.labels(endpoint=endpoint, method=request.method).inc()
		metrics['concurrent'].labels(endpoint=endpoint, method=request.method, **request_store.labels).inc()
		request_store.start_time = monotonic()
		return fn(**kwargs)

	return _stats


def after_request(response):
	"""Must be registered to run after requests. Finishes tracking the request
	and logs most of the metrics.
	We do it in this way, instead of inside the request_stats wrapper, because it lets flask
	normalize the handler result into a Response object.
	"""
	if 'metrics' not in request_store:
		return response # untracked handler

	end_time = monotonic()
	metrics = request_store.metrics
	endpoint = request_store.endpoint
	method = request_store.method
	labels = request_store.labels
	start_time = request_store.start_time

	generic_concurrent.labels(endpoint=endpoint, method=method).dec()
	metrics['concurrent'].labels(endpoint=endpoint, method=method, **labels).dec()

	status = str(response.status_code)
	generic_latency.labels(endpoint=endpoint, method=method, status=status).observe(end_time - start_time)
	metrics['latency'].labels(endpoint=endpoint, method=method, status=status, **labels).observe(end_time - start_time)
	size = response.calculate_content_length()
	if size is not None:
		generic_size.labels(endpoint=endpoint, method=method, status=status).observe(size)
		metrics['size'].labels(endpoint=endpoint, method=method, status=status, **labels).observe(size)

	return response
