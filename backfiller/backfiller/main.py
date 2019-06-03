"""Download segments from other nodes to catch stuff this node missed."""

import datetime
import errno
import logging
import os
import random
import signal
import socket
import urlparse
import uuid

import argh
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
TIMEOUT = 5 #default timeout in seconds for remote requests or exceptions 
MAX_RETRIES = 4 #number of times to retry before stopping worker or manager


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
		hours = [hour for hour in hours if datetime.datetime.strptime(hour, HOUR_FMT) > start]
	
	return hours


class BackfillerManager(object):
	"""Manages BackfillerWorkers to backfill from a pool of nodes.

	The manager regularly calls get_nodes to an up to date list of nodes. If no
	worker exists for a node in this list or in the static_node list, the
	manager starts one. If a worker corresponds to a node not in either list,
	the manager stops it. If run_once, only backfill once."""

	NODE_INTERVAL = 300 #seconds between updating list of nodes

	def __init__(self, base_dir, stream, variants, static_nodes=[], start=None,
			run_once=False, node_file=None, node_database=None, localhost=None):
		"""Constructor for BackfillerManager.
		Creates a manager for a given stream with specified variants. If
		static_nodes is None, manager"""
		self.base_dir = base_dir
		self.stream = stream
		self.variants = variants
		self.static_nodes = static_nodes
		self.start = start
		self.run_once = run_once
		self.node_file = node_file
		self.node_database = node_database
		self.localhost = localhost
		self.stopping = gevent.event.Event()
		self.logger = logging.getLogger("BackfillerManager({})".format(stream))
		self.workers = {} # {node url: worker}

	def stop(self):
		"""Shut down all workers and stop backfilling."""
		self.logger.info('Stopping')
		for node in self.workers.keys():
			self.stop_worker(node)
		self.stopping.set()

	def start_worker(self, node):
		"""Start a new worker for given node."""
		if self.stopping.is_set():
			logging.debug('Refusing to create new workers because we are stopping')
			return
		worker = BackfillerWorker(self, node)
		assert node not in self.workers, "Tried to start worker for node {!r} that already has one".format(node)
		self.workers[node] = worker
		gevent.spawn(worker.run)

	def stop_worker(self, node):
		"""Stop the worker for given node."""
		self.workers.pop(node).stop()

	def run(self):
		"""Stop and start workers based on results of get_nodes.
		
		Regularly call get_nodes. Nodes returned by get_nodes not currently
		running are started and currently running nodes not returned by
		get_nodes are stopped. If self.run_once, only call nodes once. Calling
		stop will exit the loop."""
		self.logger.info('Starting')
		failures = 0

		while not self.stopping.is_set():
			try:
				new_nodes = set(self.get_nodes())
			except Exception:
				failures += 1
				if failures > MAX_RETRIES:
					self.logger.exception('Maximum number of failures ({}) exceed.'.format(MAX_RETRIES))
					break
				delay = common.jitter(TIMEOUT * 2**failures)
				self.logger.exception('Getting nodes failed. Retrying in {:.0f} s'.format(delay))
				self.stopping.wait(delay)
				continue
			exisiting_nodes = set(self.workers.keys())
			to_start = new_nodes - exisiting_nodes
			for node in to_start:
				self.start_worker(node)
			to_stop = exisiting_nodes - new_nodes
			for node in to_stop:
				self.stop_worker(node)
			failures = 0 #reset failures on success
			if self.run_once:
				break

			self.stopping.wait(common.jitter(self.NODE_INTERVAL))

		#wait for all workers to finish
		for worker in self.workers.values():
			worker.done.wait()

	def get_nodes(self):
		"""List address of other wubloaders.
		
		This returns a list of the other wubloaders as URL strings.
		
		If only has a URL, infer name from the hostname of the URL"""

		nodes = {urlparse.urlparse(node).hostname:node for node in self.static_nodes}
		
		if self.node_file is not None:
			self.logger.info('Fetching list of nodes from {}'.format(self.node_file))
			with open(self.node_file) as f:
				for line in f.readlines():
					substrs = line.split()
					if not len(line) or substrs[0][0] == '#':
						continue
					elif len(substrs) == 1:
						nodes[urlparse.urlparse(substrs[0]).hostname] = substrs[0]
					else:
						nodes[substrs[0]] = substrs[1]

		if self.node_database is not None:
			self.logger.info('Fetching list of nodes from {}'.format(self.node_database))
			# TODO query the database

		nodes.pop(self.localhost, None)
		return nodes.values()

class BackfillerWorker(object):
	"""Backfills segments from a node.

	Backfills every WAIT_INTERVAL all segments from node/stream to
	base_dir/stream for all variants. If run_once, only backfill once.""" 

	WAIT_INTERVAL = 120 #seconds between backfills

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
	
					# to avoid getting in the downloader's way ignore segments
					# less than recent_cutoff old
					if datetime.datetime.utcnow() - segment.start < datetime.timedelta(seconds=recent_cutoff):
						self.logger.debug('Skipping {} as too recent'.format(path))
						continue
	
					get_remote_segment(self.base_dir, self.node, self.stream, variant, hour, missing_segment)
				self.logger.info('{} segments in {}/{} backfilled'.format(len(missing_segments), variant, hour))

	def run(self):
		self.logger.info('Starting')
		failures = 0

		while not self.stopping.is_set():

			try:
				self.backfill(list_hours(self.node, self.stream, self.variants, self.start))
				failures = 0 #reset failure count on a successful backfill
				if not self.run_once:
					self.stopping.wait(common.jitter(self.WAIT_INTERVAL))

			except Exception:
				failures += 1
				if failures > MAX_RETRIES:
					self.logger.exception('Maximum number of failures ({}) exceed.'.format(MAX_RETRIES))
					break
				delay = common.jitter(TIMEOUT * 2**failures)
				self.logger.exception('Backfill failed. Retrying in {:.0f} s'.format(delay))
				self.stopping.wait(delay)

			if self.run_once:
				break
		
		self.logger.info('Worker stopped')
		self.done.set()
		if self.node in self.manager.workers:
			del self.manager.workers[self.node]

@argh.arg("streams", nargs="*")
@argh.arg('--base-dir', help='Directory to which segments will be backfilled. Default is current working directory.')
@argh.arg('--variants', help="Variants of each stream to backfill. Comma seperated if multiple. Default is 'source'.")
@argh.arg('--metrics-port', help='Port for Prometheus stats. Default is 8002.')
@argh.arg('--static-nodes', help='Nodes to always backfill from. Comma seperated if multiple. By default empty.')
@argh.arg('--backdoor-port', help='Port for gevent.backdoor access. By default disabled.')
@argh.arg('--start', help='If a datetime only backfill hours after that datetime. If a number, bacfill hours more recent than that number of hours ago. If None (default), all hours are backfilled.')
@argh.arg('--run-once', help='If True, backfill only once. By default False.')
@argh.arg('--node-file', help="Name of file listing nodes to backfill from. One node per line in the form NAME URI with whitespace only lines or lines starting with '#' ignored. If None (default) do not get nodes from a file.")
@argh.arg('--node-database', help='Address of database node to fetch a list of nodes from. If None (default) do not get nodes from database.')
@argh.arg('--localhost', help='Name of local machine. Used to prevent backfilling from itself. By default the result of socket.gethostname()')
def main(streams, base_dir='.', variants='source', metrics_port=8002,
	static_nodes='', backdoor_port=0, start=None, run_once=False,
	node_file=None, node_database=None, localhost=socket.gethostname()):
	"""Backfiller service."""

	variants = variants.split(',') if variants else []
	variants = [variant.strip() for variant in variants]
	static_nodes = static_nodes.split(',') if static_nodes else []
	static_nodes = [static_node.strip() for static_node in static_nodes]

	if start is not None:
		try:
			start = float(start)
			logging.info('Backfilling last {} hours'.format(start))
		except ValueError:
			start = dateutil.parser.parse(start)
			logging.info('Backfilling since {}'.format(start)) 

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	managers = []
	workers = []
	for stream in streams:
		logging.info('Starting backfilling {} with {} as variants to {}'.format(stream, ', '.join(variants), base_dir))
		manager = BackfillerManager(base_dir, stream, variants, static_nodes, start, run_once, node_file, node_database, localhost)
		managers.append(manager)
		workers.append(gevent.spawn(manager.run))

	def stop():
		for manager in managers:
			manager.stop()

	gevent.signal(signal.SIGTERM, stop)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	# Wait for any to die
	gevent.wait(workers, count=1)
	# If one has stopped, either:
	# 1. stop() was called and all are stopping
	# 2. one errored and we should stop all remaining and report the error
	# Our behaviour in both cases is the same:
	# 1. Tell all managers to gracefully stop
	stop()
	# 2. Wait (with timeout) until they've stopped
	gevent.wait(workers)
	# 3. Check if any of them failed. If they did, report it. If mulitple
	#    failed, we report one arbitrarily.
	for worker in workers:
		worker.get()

	logging.info('Gracefully stopped')
