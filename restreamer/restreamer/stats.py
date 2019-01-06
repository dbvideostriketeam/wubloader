
import functools

import prometheus_client as prom
from flask import request
from flask import g as request_store
from monotonic import monotonic


def stats(fn):
	"""Decorator that wraps a handler func to collect metrics.
	Adds handler func args as labels, along with 'endpoint' label using func's name,
	method and response status where applicable."""
	# We have to jump through some hoops here, because the prometheus client lib demands
	# we pre-define our label names, but we don't know the names of the handler kwargs
	# until the first time the function's called. So we delay defining the metrics until
	# first call.
	metrics = {}
	endpoint = fn.__name__

	@functools.wraps(fn)
	def _stats(**kwargs):
		if not metrics:
			# first call, set up metrics
			labels_no_status = sorted(kwargs.keys()) + ['endpoint', 'method']
			labels = labels_no_status + ['status']
			metrics['latency'] = prom.Histogram(
				'http_request_latency',
				'Time taken to run the request handler and create a response',
				labels,
				# buckets: very long playlists / cutting can be quite slow,
				# so we have a wider range of latencies than default, up to 10min.
				buckets=[.001, .005, .01, .05, .1, .5, 1, 5, 10, 30, 60, 120, 300, 600],
			)
			metrics['size'] = prom.Histogram(
				'http_response_size',
				'Size in bytes of response body for non-chunked responses',
				labels,
				# buckets: powers of 4 up to 1GiB (1, 4, 16, 64, 256, 1Ki, 4Ki, ...)
				buckets=[4**i for i in range(16)],
			)
			metrics['concurrent'] = prom.Gauge(
				'http_request_concurrency',
				'Number of requests currently ongoing',
				labels_no_status,
			)

		request_store.metrics = metrics
		request_store.labels = {k: str(v) for k, v in kwargs.items()}
		request_store.labels.update(endpoint=endpoint, method=request.method)
		metrics['concurrent'].labels(**request_store.labels).inc()
		request_store.start_time = monotonic()
		return fn(**kwargs)

	return _stats


def after_request(response):
	"""Must be registered to run after requests. Finishes tracking the request
	and logs most of the metrics.
	We do it in this way, instead of inside the stats wrapper, because it lets flask
	normalize the handler result into a Response object.
	"""
	if 'metrics' not in request_store:
		return response # untracked handler

	end_time = monotonic()
	metrics = request_store.metrics
	labels = request_store.labels
	start_time = request_store.start_time

	metrics['concurrent'].labels(**labels).dec()

	labels['status'] = str(response.status_code)
	metrics['latency'].labels(**labels).observe(end_time - start_time)
	size = response.calculate_content_length()
	if size is not None:
		metrics['size'].labels(**labels).observe(size)

	return response
