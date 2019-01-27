"""Download segments from other nodes to catch stuff this node missed."""
# TODO more logging, better exception handling

import datetime
import errno
import logging
import os
import random
import time
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
TIMEOUT = 5 #default timeout for remote requests 

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
	# nodes so that 
	# as a prototype can just hardcode some addresses.

	logging.info('Fetching list of other nodes')

	nodes = ['http://toodles.videostrike.team:1337/']
	#nodes = []
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


def backfill_nodes(base_dir, stream, variants, hours=None, nodes=None, start=None):
	"""Loop over nodes backfilling from each.

	Backfill from node/stream/variants to base_dir/stream/variants for each node
	in nodes. If nodes is None, use get_nodes() to get a list of nodes to
	backfill from. By default all hours are backfilled. If backfilling from a
	node raises an exception, this just goes onto the next node."""

	if nodes is None:
		nodes = get_nodes()

	#ideally do this in parallel
	for node in nodes:
		try:
			backfill(base_dir, node, stream, variants, hours)
		except Exception:
			logging.exception("Error while backfilling node {}".format(node))


def last_hours(n_hours=3):
	"""Return of a list of the last n_hours in descending order."""
	if n_hours < 1:
		raise ValueError('Number of hours has to be 1 or greater')
	now = datetime.datetime.utcnow()
	return [(now - i * datetime.timedelta(hours=1)).strftime(HOUR_FMT) for i in range(n_hours)]


def list_hours(node, stream, variants, order='forward', start=None):
	"""Return a list of all available hours from a node.

	List all hours available from node/stream for each variant in variants.
	
	Keyword arguments:
	order -- If 'random', randomise the order of segments. If 'forward', sort
		the hours in ascending order. If 'reverse' (default), sort the
		hours in descending order. Otherwise, do not change the order of the
		hours.
	start -- Only return hours after this time. If None (default), all hours are
	returned."""

	hour_lists = [list_remote_hours(node, stream, variant) for variant in variants]
	hours = list(set().union(*hour_lists))

	if start is not None:
		hours = [hour for hour in hours if datetime.datetime.strptime(hour, HOUR_FMT) < start]

	if order == 'random':
		random.shuffle(hours)
	elif order == 'forward':
		hours.sort()
	elif order == 'reverse':
		hours.sort(reverse=True)
	
	return hours


def backfill(base_dir, node, stream, variants, hours, segment_order='random', recent_cutoff=60):
	"""Backfill from remote node.

	Backfill from node/stream/variants to base_dir/stream/variants for each hour
	in hours.

	Keyword arguments:
	segment_order -- If 'random', randomise the order of segments (default).
		If 'forward', sort the segment in ascending order. If 'reverse', sort
		the segments in descending order. Otherwise, do not change the order of
		segments.
	recent_cutoff -- Skip backfilling segments younger than this number of
		seconds to prioritise letting the downloader grab these segments."""

	logging.info('Starting backfilling from {}'.format(node))

	for variant in variants:

		for hour in hours:

			logging.info('Backfilling {}/{}/{}'.format(stream, variant, hour))

			local_segments = set(list_local_segments(base_dir, stream, variant, hour))
			remote_segments = set(list_remote_segments(node, stream, variant, hour))
			missing_segments = list(remote_segments - local_segments)

			# useful if running in parallel so multiple nodes don't request the same segment at the same time
			if segment_order == 'random':
				random.shuffle(missing_segments)
			elif segment_order == 'forward':
				missing_segments.sort()
			elif segment_order == 'reverse':
				missing_segments.sort(reverse=True)

			for missing_segment in missing_segments:

				path = os.path.join(stream, variant, hour, missing_segment)

				# test to see if file is a segment and get the segments start time
				try:
					segment = common.parse_segment_path(path)
				except ValueError as e:
					logging.warning('File {} invaid: {}'.format(path, e))
					continue

				#to avoid getting in the downloader's way ignore segments less than recent_cutoff old
				if datetime.datetime.utcnow() - segment.start < datetime.timedelta(seconds=recent_cutoff):
					logging.debug('Skipping {} as too recent'.format(path))
					continue

				get_remote_segment(base_dir, node, stream, variant, hour, missing_segment)
			logging.info('{} segments in {}/{}/{} backfilled'.format(len(missing_segments), stream, variant, hour))

	logging.info('Finished backfilling from {}'.format(node))

class BackfillerManager(object):
	"""Manages BackfillerWorkers to backfill from a pool of nodes.

	The manager regularly calls get_nodes to an up to date list of nodes. If no
	worker exists for a node, the manager starts one. If a worker corresponds to
	a node not in the list, the manager stops it."""

	NODE_INTERVAL = 5 #minutes between updating list of nodes

	def __init__(self, base_dir, stream, variants, input_nodes=None):
		"""Constructor for BackfillerManager."""
		self.base_dir = base_dir
		self.stream = stream
		self.variants = variants
		self.stopping = gevent.event.Event()
		self.workers = {} # {node url: worker}


	def stop(self):
		"""Shut down all workers and stop backfilling."""
		self.logger.info('Stopping')
		self.stopping.set()


	def start_worker(self, node):
		"""Start a new worker for given node."""
		worker = BackfillerWorker(self, self.base_dir, node, self.stream, self.variants)
		if node in self.workers:
			self.workers[node].stop() #only one worker per node
		self.workers[node] = worker
		gevent.spawn(worker.run)
		

	def stop_worker(self, node):
		"""Stop the worker for given node."""
		self.workers[node].stop()
		del self.workers[node]


	def run(self):
		while not self.stopping.is_set():
			new_nodes = set(get_nodes())
			exisiting_nodes = set(self.workers.keys())

			to_start = new_nodes - exisiting_nodes
			for node in to_start:
				self.start_worker(node)

			to_stop = exisiting_nodes - new_nodes
			for node in to_stop:
				self.stop_worker(node)

			self.stopping.wait(common.jitter(self.NODE_INTERVAL * 60))

		for worker in self.workers:
			worker.stop()
		for worker in self.workers:
			worker.done.wait()


class BackfillerWorker(object):
	"""Backfills segments from a node.

	Backfills all segments from node/stream to base_dir/stream for all variants.
	Every SMALL_INTERVAL minutes backfill the last three hours starting from the
	most recent one (a 'small backfill'). When not doing a small backfill,
	backfill all segments starting with the most recent one (a 'large backfill')
	unless a large backfill has occured less than LARGE_INTERVAL ago.""" 

	SMALL_INTERVAL = 5 #minutes between small backfills
	LARGE_INTERVAL = 60 #minutes between large backfills
	WAIT_INTERVAL = 1 #seconds between backfill actions

	def __init__(self, manager, base_dir, node, stream, variants):
		"""Constructor for BackfillerWorker"""
		self.manager = manager
		self.logger = manager.logger.getChild('BackfillerWorker({}/{})@{:x}'.format(node, stream, id(self)))
		self.base_dir = base_dir
		self.node = node
		self.stream = stream
		self.variants = variants
		self.stopping = gevent.event.Event()
		self.done = gevent.event.Event()

	def __repr__(self):
			return '<{} at 0x{:x} for {!r}/{!r}>'.format(type(self).__name__, id(self), self.node, self.stream)
	__str__ = __repr__

	def stop(self):
		"""Tell the worker to shut down"""
		self.stopping.set()

	def trigger_new_worker(self):
		self.manager.trigger_new_worker(self)

	def run(self):
		self.logger.info('Worker starting')
		try:
			self._run()
		except Exception:
			self.logger.exception('Worker failed')
		else:
			self.logger.info('Worker stopped')
		finally:
			self.done.set()
			del self.manager.workers[self.node]

	def _run(self):
		
		last_small_backfill = datetime.datetime.now() + datetime.timedetla(-1)
		last_large_backfill = datetime.datetime.now() + datetime.timedetla(-1)
		large_hours = []

		while not self.stopping.is_set():

			now = datetime.datetime.now()

			if now - last_small_backfill > datetime.timedelta(minutes=self.SMALL_INTERVAL):
				backfill(self.base_dir, self.node, self.stream, self.variants, last_hours())
				last_small_backfill = now

			elif now - last_large_backfill > datetime.timedelta(minutes=self.LARGE_INTERVAL) or len(large_hours):
				if not len(large_hours):
					large_hours = list_hours(self.node, self.stream, self.variants)
					last_large_backfill = now

				this_hour = large_hours[-1:]
				large_hours = large_hours[:-1]
				backfill(self.base_dir, self.node, self.stream, self.variants, this_hour)
			else:	
				self.stopping.wait(common.jitter(self.WAIT_INTERVAL))	

							
def main(base_dir='.', stream='', variants='', fill_wait=5, full_fill_wait=180, sleep_time=1, metrics_port=8002, nodes=None, backdoor_port=0, start=None):
	"""Prototype backfiller service.

	Do a backfill of the last 3 hours from stream/variants from all nodes
	initially before doing a full backfill from all nodes. Then every sleep_time
	minutes check to see if more than fill_wait minutes have passed since the	
	last backfill. If so do a backfill of the last 3 hours. Also check whether
	it has been more than full_fill_wait minutes since the last full backfill;
	if so, do a full backfill."""
	# TODO replace this with a more robust event based service and backfill from multiple nodes in parallel
	# stretch goal: provide an interface to trigger backfills manually
	# stretch goal: use the backfiller to monitor the restreamer

	variants = variants.split(',') if variants else []
	if nodes is not None:
		nodes = nodes.split(',') if nodes else []
	if start is not None:
		start = dateutil.parser.parse(start)

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	logging.info('Starting backfilling {} with {} as variants to {}'.format(stream, ', '.join(variants), base_dir))

	fill_start = datetime.datetime.now()
	full_fill_start = fill_start

	
	backfill(base_dir, stream, variants, 3, nodes=nodes, start=start)

	backfill(base_dir, stream, variants, nodes=nodes, start=start)
	
	# I'm sure there is a module that does this in a more robust way 
	# but I understand this and it gives the behaviour I want
	while True:

		now = datetime.datetime.now()

		if now - full_fill_start > datetime.timedelta(minutes=full_fill_wait):

			backfill(base_dir, stream, variants, nodes=nodes, start=start)

			fill_start = now
			full_fill_start = fill_start

		elif now - fill_start > datetime.timedelta(minutes=fill_wait):

			backfill(base_dir, stream, variants, 3, nodes=nodes, start=start)

			fill_start = now

		else:
			time.sleep(common.jitter(60 * sleep_time))

