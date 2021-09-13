"""Download segments from other nodes to catch stuff this node missed."""

import datetime
import errno
import hashlib
import itertools
import logging
import os
import random
import signal
import socket
import urllib.parse
import uuid

import argh
import gevent.backdoor
import gevent.pool
import prometheus_client as prom

import common
from common import dateutil
from common import database
from common.requests import InstrumentedSession

# Wraps all requests in some metric collection
requests = InstrumentedSession()

segments_backfilled = prom.Counter(
	'segments_backfilled',
	'Number of segments successfully backfilled',
	['remote', 'channel', 'quality', 'hour'],
)

hours_backfilled = prom.Counter(
	'hours_backfilled',
	'Number of hours successfully backfilled',
	['remote', 'channel', 'quality'],
)

hash_mismatches = prom.Counter(
	'hash_mismatches',
	'Number of segments with hash mismatches',
	['remote', 'channel', 'quality', 'hour'],
)

node_list_errors = prom.Counter(
	'node_list_errors',
	'Number of errors fetching a list of nodes',
)

backfill_errors = prom.Counter(
	'backfill_errors',
	'Number of errors backfilling',
	['remote'],
)

segments_deleted = prom.Counter(
	'segments_deleted',
	'Number of segments successfully deleted',
	['channel', 'quality', 'hour'],
)

HOUR_FMT = '%Y-%m-%dT%H'
TIMEOUT = 5 #default timeout in seconds for remote requests or exceptions 
MAX_BACKOFF = 4 #number of times to back off

def list_local_hours(base_dir, channel, quality):
	"""List hours in a given quality directory.

	For a given base_dir/channel/quality directory return a list of
	non-hidden files. If the directory path is not found, return an empty list. 

	Based on based on restreamer.list_hours. We could just call
	restreamer.list_hours but this avoids HTTP/JSON overheads."""

	path = os.path.join(base_dir, channel, quality)
	try:
		return [name for name in os.listdir(path) if not name.startswith('.')]

	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		return []	


def list_local_segments(base_dir, channel, quality, hour):
	"""List segments in a given hour directory.

	For a given base_dir/channel/quality/hour directory return a list of
	non-hidden files. If the directory path is not found, return an empty list. 

	Based on based on restreamer.list_segments. We could just call
	restreamer.list_segments but this avoids HTTP/JSON overheads."""

	path = os.path.join(base_dir, channel, quality, hour)
	try:
		return [name for name in os.listdir(path) if not name.startswith('.')]

	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		return []	


def list_remote_hours(node, channel, quality, timeout=TIMEOUT):
	"""Wrapper around a call to restreamer.list_hours."""
	uri = '{}/files/{}/{}'.format(node, channel, quality)
	logging.debug('Getting list of hours from {}'.format(uri))
	resp = requests.get(uri, timeout=timeout, metric_name='list_remote_hours')
	return resp.json()


def list_remote_segments(node, channel, quality, hour, timeout=TIMEOUT):
	"""Wrapper around a call to restreamer.list_segments."""
	uri = '{}/files/{}/{}/{}'.format(node, channel, quality, hour)
	logging.debug('Getting list of segments from {}'.format(uri))
	resp = requests.get(uri, timeout=timeout, metric_name='list_remote_segments')
	return resp.json()


def get_remote_segment(base_dir, node, channel, quality, hour, missing_segment, 
		logger, timeout=TIMEOUT):
	"""Get a segment from a node.

	Fetches channel/quality/hour/missing_segment from node and puts it in
	base_dir/channel/quality/hour/missing_segment. If the segment already exists
	locally, this does not attempt to fetch it."""

	path = os.path.join(base_dir, channel, quality, hour, missing_segment)
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
	hash = hashlib.sha256()

	try:
		logging.debug('Fetching segment {} from {}'.format(path, node))
		uri = '{}/segments/{}/{}/{}/{}'.format(node, channel, quality, hour, missing_segment)
		resp = requests.get(uri, stream=True, timeout=timeout, metric_name='get_remote_segment')

		resp.raise_for_status()

		with open(temp_path, 'wb') as f:
			for chunk in resp.iter_content(8192):
				common.writeall(f.write, chunk)
				hash.update(chunk)

		filename_hash = common.parse_segment_path(missing_segment).hash
		if filename_hash != hash.digest():
			logger.warn('Hash of segment {} does not match. Discarding segment'.format(missing_segment))
			hash_mismatches.labels(remote=node, channel=channel, quality=quality, hour=hour).inc()
			os.remove(temp_path)
			return 

	#try to get rid of the temp file if an exception is raised.
	except Exception:
		if os.path.exists(temp_path):
			os.remove(temp_path)
		raise
	logging.debug('Saving completed segment {} as {}'.format(temp_path, path))
	common.rename(temp_path, path)
	segments_backfilled.labels(remote=node, channel=channel, quality=quality, hour=hour).inc()
	logger.info('Segment {}/{}/{} backfilled'.format(quality, hour, missing_segment))


def list_hours(node, channel, quality, start=None):
	"""Return a list of all available hours from a node.

	List all hours available from node/channel
	ordered from newest to oldest.
	
	Keyword arguments:
	start -- If a datetime return hours after that datetime. If a number,
	return hours more recent than that number of hours ago. If None (default),
	all hours are returned."""

	hours = list_remote_hours(node, channel, quality)
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
	the manager stops it. If run_once, only backfill once. If delete_old,
	delete hours older than start. The deletion is handled by the Manager as
	having the Workers do it could lead to race conditions."""

	NODE_INTERVAL = 300 #seconds between updating list of nodes

	def __init__(self, base_dir, channels, qualities, static_nodes=[],
			start=None, delete_old=False, run_once=False, node_file=None,
			node_database=None, localhost=None, download_concurrency=5,
			recent_cutoff=120):
		"""Constructor for BackfillerManager.

		Creates a manager for a given channel with specified qualities."""
		self.base_dir = base_dir
		self.channels = channels
		self.qualities = qualities
		self.static_nodes = static_nodes
		self.start = start
		self.delete_old = delete_old
		self.run_once = run_once
		self.node_file = node_file
		self.db_manager = None if node_database is None else database.DBManager(dsn=node_database)
		self.connection = None
		self.localhost = localhost
		self.download_concurrency = download_concurrency
		self.recent_cutoff = recent_cutoff
		self.stopping = gevent.event.Event()
		self.logger = logging.getLogger("BackfillerManager")
		self.workers = {} # {node url: worker}

	def stop(self):
		"""Shut down all workers and stop backfilling."""
		self.logger.info('Stopping')
		for node in list(self.workers.keys()):
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

	def delete_hours(self):
		"""Delete hours older than self.start ago."""

		if isinstance(self.start, datetime.datetime):
			self.logger.info('Deleting hours older than {}'.format(self.start.strftime(HOUR_FMT)))
		else:
			self.logger.info('Deleting hours older than {} hours ago'.format(self.start))

		for channel, quality in itertools.product(self.channels, self.qualities):
			hours = list_local_hours(self.base_dir, channel, quality)
			if not isinstance(self.start, datetime.datetime):
				cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=self.start)
			else:
				cutoff = self.start
			hours = [hour for hour in hours if datetime.datetime.strptime(hour, HOUR_FMT) < cutoff]
			hours.sort()

			for hour in hours:
				# deleting segments can take a bit time but is less important
				# than the actually backfilling so we yield
				gevent.idle()
				path = os.path.join(self.base_dir, channel, quality, hour)
				self.logger.info('Deleting {}'.format(path))
				segments = list_local_segments(self.base_dir, channel, quality, hour)
				for segment in segments:
					try:
						os.remove(os.path.join(path, segment))
						segments_deleted.labels(channel=channel, quality=quality, hour=hour).inc()
					except OSError as e:
						# ignore error when the file is already gone
						if e.errno != errno.ENOENT:
							raise

				try:
					os.rmdir(path)
				except OSError as e:
					# ignore error when file is already deleted
					if e.errno == errno.ENOENT:
						self.logger.warn('{} already deleted'.format(path))
					# warn if not empty (will try to delete folder again next time) 
					elif e.errno == errno.ENOTEMPTY:
						self.logger.warn('Failed to delete non-empty folder {}'.format(path))
					else:
						raise
				else:
					self.logger.info('{} deleted'.format(path))


		self.logger.info('Deleting old hours complete')		

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
				# To ensure a fresh slate and clear any DB-related errors, get a new conn on error.
				# This is heavy-handed but simple and effective.
				self.connection = None
				if failures < MAX_BACKOFF:
					failures += 1
				delay = common.jitter(TIMEOUT * 2**failures)
				self.logger.exception('Getting nodes failed. Retrying in {:.0f} s'.format(delay))
				node_list_errors.inc()
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

			# note that if get_nodes() raises an error, then deletes will not occur
			if self.delete_old and self.start:
				try:
					self.delete_hours()
				except Exception:
					self.logger.warning('Failed to delete old segments', exc_info=True)

			self.stopping.wait(common.jitter(self.NODE_INTERVAL))

		#wait for all workers to finish
		for worker in list(self.workers.values()):
			worker.done.wait()

	def get_nodes(self):
		"""List address of other wubloaders.
		
		This returns a list of the other wubloaders as URL strings. Node URLs
		are taken from three places. First, the --static-nodes command line
		argument can be used to provide a list of URLs that are always
		backfilled from. Node names are infered from the hostnames of the URLs.
		Second, nodes are read from the file named in the --node-file command
		line argument. In this file, nodes are listed one per line as name-URL
		pairs or as just node URLs. Lines starting with '#' are ignored. If
		only the URL is provided, the node name is taken from the hostname.
		Third, node names and URLs can be requested from the database given by
		--node-database. If multiple nodes URLs with the same name are found,
		only the last is retained and any nodes with names matching the
		localhost name (given by the --localhost argument) are ignored to try
		to prevent this node from backfilling from itself."""

		nodes = {urllib.parse.urlparse(node).hostname: node for node in self.static_nodes}
		
		if self.node_file is not None:
			self.logger.info('Fetching list of nodes from {}'.format(self.node_file))
			with open(self.node_file) as f:
				for line in f.readlines():
					substrs = line.split()
					if not len(line) or substrs[0][0] == '#':
						continue
					elif len(substrs) == 1:
						nodes[urllib.parse.urlparse(substrs[0]).hostname] = substrs[0]
					else:
						nodes[substrs[0]] = substrs[1]

		if self.db_manager is not None:
			if self.connection is None:
				self.connection = self.db_manager.get_conn()
			host = [s.split('=')[-1] for s in self.connection.dsn.split() if 'host' in s][0]
			self.logger.info('Fetching list of nodes from {}'.format(host))
			results = database.query(self.connection, """
				SELECT name, url
				FROM nodes
				WHERE backfill_from""")
			for row in results:
				nodes[row.name] = row.url
		nodes.pop(self.localhost, None)
		self.logger.info('Nodes fetched: {}'.format(list(nodes.keys())))
		return list(nodes.values())

class BackfillerWorker(object):
	"""Backfills segments from a node.

	Backfills every WAIT_INTERVAL all segments from node/channel to
	base_dir/channel for all qualities. If run_once, only backfill once.

	recent_cutoff -- Skip backfilling segments younger than this number of
		seconds to prioritise letting the downloader grab these segments.
	"""

	WAIT_INTERVAL = 120 #seconds between backfills

	def __init__(self, manager, node):
		self.manager = manager
		self.logger = manager.logger.getChild('BackfillerWorker({})'.format(node))
		self.base_dir = manager.base_dir
		self.node = node
		self.download_concurrency = manager.download_concurrency
		self.channels = manager.channels
		self.qualities = manager.qualities
		self.start = manager.start
		self.run_once = manager.run_once
		self.recent_cutoff = manager.recent_cutoff
		self.stopping = gevent.event.Event()
		self.done = gevent.event.Event()

	def __repr__(self):
			return '<{} at 0x{:x} for {!r}>'.format(type(self).__name__, id(self), self.node)
	__str__ = __repr__

	def stop(self):
		"""Tell the worker to shut down"""
		self.logger.info('Stopping')
		self.stopping.set()

	def backfill(self):
		"""Backfill from remote node.
	
		Backfill from node/channel/qualities to base_dir/channel/qualities for
		each hour in hours.
		"""
		for channel, quality in itertools.product(self.channels, self.qualities):
			for hour in list_hours(self.node, channel, quality, self.start):
				# since backfilling can take a long time, recheck whether this
				# hour is after the start
				if self.start is not None:
					if not isinstance(self.start, datetime.datetime):
						start_hour = datetime.datetime.utcnow() - datetime.timedelta(hours=self.start)
					else:
						start_hour = self.start
					if datetime.datetime.strptime(hour, HOUR_FMT) < start_hour:
						break

				self.logger.info('Backfilling {}/{}'.format(quality, hour))
	
				local_segments = set(list_local_segments(self.base_dir, channel, quality, hour))
				remote_segments = set(list_remote_segments(self.node, channel, quality, hour))
				missing_segments = list(remote_segments - local_segments)
	
				# randomise the order of the segments to reduce the chance that
				# multiple workers request the same segment at the same time
				random.shuffle(missing_segments)

				pool = gevent.pool.Pool(self.download_concurrency)
				workers = []
	
				for missing_segment in missing_segments:
	
					if self.stopping.is_set():
						return

					path = os.path.join(channel, quality, hour, missing_segment)
	
					# test to see if file is a segment and get the segments start time
					try:
						segment = common.parse_segment_path(path)
					except ValueError as e:
						self.logger.warning('File {} invalid: {}'.format(path, e))
						continue

					# Ignore temp segments as they may go away by the time we fetch them.
					if segment.type == "temp":
						self.logger.debug('Skipping {} as it is a temp segment'.format(path))
						continue
	
					# to avoid getting in the downloader's way ignore segments
					# less than recent_cutoff old
					if datetime.datetime.utcnow() - segment.start < datetime.timedelta(seconds=self.recent_cutoff):
						self.logger.debug('Skipping {} as too recent'.format(path))
						continue
	
					# start segment as soon as a pool slot opens up, then track it in workers
					workers.append(pool.spawn(
						get_remote_segment,
						self.base_dir, self.node, channel, quality, hour, missing_segment, self.logger
					))

				# verify that all the workers succeeded. if any failed, raise the exception from
				# one of them arbitrarily.
				for worker in workers:
					worker.get() # re-raise error, if any

				self.logger.info('{} segments in {}/{} backfilled'.format(len(workers), quality, hour))
				hours_backfilled.labels(remote=self.node, channel=channel, quality=quality).inc()


	def run(self):
		self.logger.info('Starting')
		failures = 0

		while not self.stopping.is_set():
			try:
				self.logger.info('Starting backfill')
				self.backfill()
				self.logger.info('Backfill complete')
				failures = 0 #reset failure count on a successful backfill
				if not self.run_once:
					self.stopping.wait(common.jitter(self.WAIT_INTERVAL))

			except Exception:
				if failures < MAX_BACKOFF:
					failures += 1
				delay = common.jitter(TIMEOUT * 2**failures)
				self.logger.exception('Backfill failed. Retrying in {:.0f} s'.format(delay))
				backfill_errors.labels(remote=self.node).inc()
				self.stopping.wait(delay)

			if self.run_once:
				break
		
		self.logger.info('Worker stopped')
		self.done.set()
		if self.node in self.manager.workers:
			del self.manager.workers[self.node]

@argh.arg('channels', nargs='*', help='Channels to backfill from')
@argh.arg('--base-dir', help='Directory to which segments will be backfilled. Default is current working directory.')
@argh.arg('--qualities', help="Qualities of each channel to backfill. Comma seperated if multiple. Default is 'source'.")
@argh.arg('--metrics-port', help='Port for Prometheus stats. Default is 8002.')
@argh.arg('--static-nodes', help='Nodes to always backfill from. Comma seperated if multiple. By default empty.')
@argh.arg('--backdoor-port', help='Port for gevent.backdoor access. By default disabled.')
@argh.arg('--start', help='If a datetime only backfill hours after that datetime. If a number, bacfill hours more recent than that number of hours ago. If None (default), all hours are backfilled.')
@argh.arg('--delete-old', help='If True, delete hours older than start. By default False.')
@argh.arg('--run-once', help='If True, backfill only once. By default False.')
@argh.arg('--node-file', help="Name of file listing nodes to backfill from. One node per line in the form NAME URI with whitespace only lines or lines starting with '#' ignored. If None (default) do not get nodes from a file.")
@argh.arg('--node-database', help='Postgres conection string for database to fetch a list of nodes from. Either a space-separated list of key=value pairs, or a URI like: postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE . If None (default) do not get nodes from database.')
@argh.arg('--localhost', help='Name of local machine. Used to prevent backfilling from itself. By default the result of socket.gethostname()')
@argh.arg('--download-concurrency', help='Max number of concurrent segment downloads from a single node. Increasing this number may increase throughput but too high a value can overload the server or cause timeouts.')
@argh.arg('--recent-cutoff', help='Minimum age for a segment before we will backfill it, to prevent us backfilling segments we could have just downloaded ourselves instead. Expressed as number of seconds.')
def main(channels, base_dir='.', qualities='source', metrics_port=8002,
	static_nodes='', backdoor_port=0, start=None, delete_old=False,
	run_once=False, node_file=None, node_database=None,
	localhost=socket.gethostname(), download_concurrency=5, recent_cutoff=120):
	"""Backfiller service."""

	qualities = qualities.split(',') if qualities else []
	qualities = [quality.strip() for quality in qualities]
	static_nodes = static_nodes.split(',') if static_nodes else []
	static_nodes = [static_node.strip() for static_node in static_nodes]

	if start is not None:
		try:
			start = float(start)
			logging.info('Backfilling last {} hours'.format(start))
		except ValueError:
			start = dateutil.parse(start)
			logging.info('Backfilling since {}'.format(start))

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	logging.info('Starting backfilling {} with {} as qualities to {}'.format(', '.join(channels), ', '.join(qualities), base_dir))
	manager = BackfillerManager(base_dir, channels, qualities, static_nodes,
			start, delete_old, run_once, node_file, node_database,
			localhost, download_concurrency, recent_cutoff)

	def stop():
		manager.stop()

	gevent.signal_handler(signal.SIGTERM, stop)

	if backdoor_port:
		gevent.backdoor.BackdoorServer(('127.0.0.1', backdoor_port), locals=locals()).start()

	manager.run()

	logging.info('Gracefully stopped')
