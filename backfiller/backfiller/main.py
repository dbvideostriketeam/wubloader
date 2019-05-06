"""Download segments from other nodes to catch stuff this node missed."""
# TODO more logging, better exception handling

import datetime
import errno
import logging
import os
import random
import signal
import uuid

import dateutil.parser
import gevent.backdoor
import prometheus_client as prom
import requests

import common


segments_backfilled = prom.Counter(
	'segments_backfilled',
	"Number of segments successfully backfilled",
	["remote", "stream", "variant", "hour"],
)


HOUR_FMT = '%Y-%m-%dT%H'
TIMEOUT = 5 #default timeout in seconds for remote requests 

def encode_strings(o):
	if isinstance(o, list):
		return [encode_strings(x) for x in o]
	if isinstance(o, dict):
		return {k.encode('utf-8'): encode_strings(v) for k, v in o.items()}
	if isinstance(o, unicode):
		return o.encode('utf-8')
	return o

def get_nodes():
	"""List address of other wubloaders.
	
	This returns a list of the other wubloaders as strings of the form
	'protocol://host:port/'"""
	# either read a config file or query the database to get the addresses
	# of the other nodes
	# figure out some way that the local machine isn't in the list of returned
	# nodes 

	logging.info('Fetching list of other nodes')

	nodes = []
	return nodes


def list_local_segments(base_dir, stream, variant, hour):
	"""List segments in a given hour directory.

	For a given base_dir/stream/variant/hour directory return a list of
	non-hidden files. If the directory path is not found, return an empty list. 

	Based on based on restreamer.list_segments. We could just call
	restreamer.list_segments but this avoids HTTP/JSON overheads."""

	path = os.path.join(base_dir, stream, variant, hour)
	try:
		return [name for name in os.listdir(path) if not name.startswith('.')]

	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		return []	


def list_remote_hours(node, stream, variant, timeout=TIMEOUT):
	"""Wrapper around a call to restreamer.list_hours."""
	uri = '{}/files/{}/{}'.format(node, stream, variant)
	logging.debug('Getting list of hours from {}'.format(uri))
	resp = requests.get(uri, timeout=timeout)
	return common.encode_strings(resp.json())


def list_remote_segments(node, stream, variant, hour, timeout=TIMEOUT):
	"""Wrapper around a call to restreamer.list_segments."""
	uri = '{}/files/{}/{}/{}'.format(node, stream, variant, hour)
	logging.debug('Getting list of segments from {}'.format(uri))
	resp = requests.get(uri, timeout=timeout)
	return common.encode_strings(resp.json())


def get_remote_segment(base_dir, node, stream, variant, hour, missing_segment,
			timeout=TIMEOUT):
	"""Get a segment from a node.

	Fetches stream/variant/hour/missing_segment from node and puts it in
	base_dir/stream/variant/hour/missing_segment. If the segment already exists
	locally, this does not attempt to fetch it."""

	path = os.path.join(base_dir, stream, variant, hour, missing_segment)
	# check to see if file was created since we listed the local segments to
	# avoid unnecessarily copying
	if os.path.exists(path):
		logging.debug('Skipping existing segment {}'.format(path))
		return
	
	dir_name = os.path.dirname(path)
	date, duration, _ = os.path.basename(path).split('-', 2)
	temp_name = "-".join([date, duration, "temp", str(uuid.uuid4())])
	temp_path = os.path.join(dir_name, "{}.ts".format(temp_name))
	common.ensure_directory(temp_path)

	try:
		logging.debug('Fetching segment {} from {}'.format(path, node))
		uri = '{}/segments/{}/{}/{}/{}'.format(node, stream, variant, hour, missing_segment)
		resp = requests.get(uri, stream=True, timeout=timeout)

		resp.raise_for_status()

		with open(temp_path, 'w') as f:
			for chunk in resp.iter_content(8192):
				f.write(chunk)

	#try to get rid of the temp file if an exception is raised.
	except Exception:
		if os.path.exists(temp_path):
			os.remove(temp_path)
		raise
	logging.debug('Saving completed segment {} as {}'.format(temp_path, path))
	common.rename(temp_path, path)
	segments_backfilled.labels(remote=node, stream=stream, variant=variant, hour=hour).inc()


def list_hours(node, stream, variants, start=None):
	"""Return a list of all available hours from a node.

	List all hours available from node/stream for each variant in variants
	ordered from newest to oldest.
	
	Keyword arguments:
	start -- If a datetime return hours after that datetime. If a number,
	return hours more recent than that number of hours ago. If None (default),
	all hours are returned."""

	hour_lists = [list_remote_hours(node, stream, variant) for variant in variants]
	hours = list(set().union(*hour_lists))
	hours.sort(reverse=True) #latest hour first


	if start is not None:
		if not isinstance(start, datetime.datetime):
			start = datetime.datetime.utcnow() - datetime.timedelta(hours=start)
		hours = [hour for hour in hours if datetime.datetime.strptime(hour, HOUR_FMT) < start]
	
	return hours


class BackfillerManager(object):
	"""Manages BackfillerWorkers to backfill from a pool of nodes.

	The manager regularly calls get_nodes to an up to date list of nodes. If no
	worker exists for a node in this list or in the static_node list, the
	manager starts one. If a worker corresponds to a node not in either list,
	the manager stops it. If run_once, only backfill once."""

	NODE_INTERVAL = 300 #seconds between updating list of nodes

	def __init__(self, base_dir, stream, variants, static_nodes=[], start=None, run_once=False):
		"""Constructor for BackfillerManager.
		Creates a manager for a given stream with specified variants. If
		static_nodes is None, manager"""
		self.base_dir = base_dir
		self.stream = stream
		self.variants = variants
		self.static_nodes = static_nodes
		self.start = start
		self.run_once = run_once
		self.stopping = gevent.event.Event()
		self.logger = logging.getLogger("BackfillerManager({})".format(stream))
		self.workers = {} # {node url: worker}

	def stop(self):
		"""Shut down all workers and stop backfilling."""
		self.logger.info('Stopping')
		for worker in self.workers:
			worker.stop()
		self.stopping.set()

	def start_worker(self, node):
		"""Start a new worker for given node."""
		worker = BackfillerWorker(self, self.base_dir, node)
		assert node not in self.workers, "Tried to start worker for node {!r} that already has one".format(node)
		self.workers[node] = worker
		gevent.spawn(worker.run)

	def stop_worker(self, node):
		"""Stop the worker for given node."""
		self.workers.pop(node).stop()

	def run(self):
		self.logger.info('Starting')
		while not self.stopping.is_set():
			new_nodes = set(get_nodes() + self.static_nodes)
			exisiting_nodes = set(self.workers.keys())
			to_start = new_nodes - exisiting_nodes
			for node in to_start:
				self.start_worker(node)
			to_stop = exisiting_nodes - new_nodes
			for node in to_stop:
				self.stop_worker(node)

			if self.run_once:
				break

			self.stopping.wait(common.jitter(self.NODE_INTERVAL))

		else:
			self.stop()

		for worker in self.workers:
			worker.done.wait()


class BackfillerWorker(object):
	"""Backfills segments from a node.

	Backfills every WAIT_INTERVAL all segments from node/stream to
	base_dir/stream for all variants. If run_once, only backfill once.""" 

	WAIT_INTERVAL = 120 #seconds between backfills
	RETRY_INTERVAL = 5 #seconds between retrying a failed backfill 

	def __init__(self, manager, node):
		self.manager = manager
		self.logger = manager.logger.getChild('BackfillerWorker({})'.format(node))
		self.base_dir = manager.base_dir
		self.node = node
		self.stream = manager.stream
		self.variants = manager.variants
		self.start = manager.start
		self.run_once = manager.run_once
		self.stopping = gevent.event.Event()
		self.done = gevent.event.Event()
		self.failures = 0


	def __repr__(self):
			return '<{} at 0x{:x} for {!r}/{!r}>'.format(type(self).__name__, id(self), self.node, self.stream)
	__str__ = __repr__

	def stop(self):
		"""Tell the worker to shut down"""
		self.logger.info('Stopping')
		self.stopping.set()

	def backfill(self, hours, segment_order='random', recent_cutoff=60):
		"""Backfill from remote node.
	
		Backfill from node/stream/variants to base_dir/stream/variants for each
		hour in hours.
	
		Keyword arguments:
		recent_cutoff -- Skip backfilling segments younger than this number of
			seconds to prioritise letting the downloader grab these segments."""
	
		for variant in self.variants:
	
			for hour in hours:
	
				self.logger.info('Backfilling {}/{}'.format(variant, hour))
	
				local_segments = set(list_local_segments(self.base_dir, self.stream, variant, hour))
				remote_segments = set(list_remote_segments(self.node, self.stream, variant, hour))
				missing_segments = list(remote_segments - local_segments)
	
				# randomise the order of the segments to reduce the chance that
				# multiple workers request the same segment at the same time
				random.shuffle(missing_segments)
	
				for missing_segment in missing_segments:
	
					if self.stopping.is_set():
						return

					path = os.path.join(self.stream, variant, hour, missing_segment)
	
					# test to see if file is a segment and get the segments start time
					try:
						segment = common.parse_segment_path(path)
					except ValueError as e:
						self.logger.warning('File {} invaid: {}'.format(path, e))
						continue
	
					#to avoid getting in the downloader's way ignore segments less than recent_cutoff old
					if datetime.datetime.utcnow() - segment.start < datetime.timedelta(seconds=recent_cutoff):
						self.logger.debug('Skipping {} as too recent'.format(path))
						continue
	
					get_remote_segment(self.base_dir, self.node, self.stream, variant, hour, missing_segment)
				self.logger.info('{} segments in {}/{} backfilled'.format(len(missing_segments), variant, hour))

	def run(self):
		self.logger.info('Starting')

		while not self.stopping.is_set():

			try:
				self.backfill(list_hours(self.node, self.stream, self.variants, self.start))
				self.failures = 0 #reset failure count on a successful backfill
				self.stopping.wait(common.jitter(self.WAIT_INTERVAL))

			except Exception:
				self.failures += 1
				delay = common.jitter(self.RETRY_INTERVAL * 2**self.failures)
				self.logger.exception('Backfill failed. Retrying in {:.0f} s'.format(delay))
				self.stopping.wait(delay)

			if self.run_once:
				break
		
		self.logger.info('Worker stopped')
		self.done.set()
		del self.manager.workers[self.node]

							
def main(base_dir='.', stream='', variants='', metrics_port=8002,
	static_nodes='', backdoor_port=0, start=None, run_once=False):
	"""Backfiller service."""

	variants = variants.split(',') if variants else []
	static_nodes = static_nodes.split(',') if static_nodes else []

	if start is not None:
		try:
			start = float(start)
		except ValueError:
			start = dateutil.parser.parse(start)

	manager = BackfillerManager(base_dir, stream, variants, static_nodes, start, run_once)
	gevent.signal(signal.SIGTERM, manager.stop)

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	logging.info('Starting backfilling {} with {} as variants to {}'.format(stream, ', '.join(variants), base_dir))
	manager.run()
	logging.info('Gracefully stopped')
