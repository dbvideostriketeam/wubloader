"""Download segments from other nodes to catch stuff this node missed."""
# TODO more logging, better exception handling

import datetime
import errno
import logging
import os
import random
import time
import uuid

import requests

import common


HOUR_FMT = '%Y-%m-%dT%H'
TIMEOUT = 5 #default timeout for remote requests 


def get_nodes():
	"""List address of other wubloaders.
	
	This returns a list of the other wubloaders as strings of the form 'protocol://host:port/'"""
	# either read a config file or query the database to get the addresses
	# of the other nodes
	# figure out some way that the local machine isn't in the list of returned
	# nodes so that 
	# as a prototype can just hardcode some addresses.

	logging.info('Fetching list of other nodes')

	nodes = []
	return nodes


def list_local_segments(base_dir, stream, variant, hour):
	"""List segments in a given hour directory.

	For a given base_dir/stream/variant/hour directory return a list of non-hidden files. If the directory path is not found, return an empty list. 

	Based on based on restreamer.list_segments. We could just call restreamer.list_segments but this avoids HTTP/JSON overheads."""

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
	return resp.json()


def list_remote_segments(node, stream, variant, hour, timeout=TIMEOUT):
	"""Wrapper around a call to restreamer.list_segments."""
	uri = '{}/files/{}/{}/{}'.format(node, stream, variant, hour)
	logging.debug('Getting list of segments from {}'.format(uri))
	resp = requests.get(uri, timeout=timeout)
	return resp.json()


def get_remote_segment(base_dir, node, stream, variant, hour, missing_segment,
			timeout=TIMEOUT):
	"""Get a segment from a node.

	Fetches stream/variant/hour/missing_segment from node and puts it in base_dir/stream/variant/hour/missing_segment. If the segment already exists locally, this does not attempt to fetch it."""

	path = os.path.join(base_dir, stream, variant, hour, missing_segment)
	logging.debug('Getting segment {}'.format(path))
	# check to see if file was created since we listed the local segments to
	# avoid unnecessarily copying
	if os.path.exists(path):
		return
	
	dir_name = os.path.dirname(path)
	date, duration, _ = os.path.basename(path).split('-', 2)
	temp_name = "-".join([date, duration, "temp", str(uuid.uuid4())])
	temp_path = os.path.join(dir_name, "{}.ts".format(temp_name))
	common.ensure_directory(temp_path)

	try:
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

	common.rename(temp_path, path)


def backfill(base_dir, stream, variants, hours=None, nodes=None, start=None,
		 stop=None, order=None):
	"""Loop over nodes backfilling from each.

	Backfill from node/stream/variants to base_dir/stream/variants for each node in nodes. If nodes is None, use get_nodes() to get a list of nodes to backfill from. Passes hours, start, stop and order to backfill_node to control which hours are backfilled and in which order. By default all hours are backfilled. If backfilling from a node raises an exception, this just goes onto the next node."""

	if nodes is None:
		nodes = get_nodes()

	#ideally do this in parallel
	for node in nodes:
		try:
			backfill_node(base_dir, node, stream, variants, hours, start, stop, order=order)
		except Exception:
			logging.exception("Error while backfilling node {}".format(node))


def is_iterable(x):
	"""Test whether input is iterable."""
	try:
 		iter(x)
	except TypeError:
		return False
	return True


def backfill_node(base_dir, node, stream, variants, hours=None, start=None,
		stop=None, hour_order=None, segment_order='random', get_full_hour=True,
		recent_cutoff=60):
	"""Backfill from remote node.

	Backfill from node/stream/variants to base_dir/stream/variants.

	Keyword arguments:
	hours -- If None (default), backfill all available hours. If iterable,
		backfill only hours in iterable. Otherwise backfill the last N hours,
		starting with the lastest.
	start -- Only backfill hours starting after or equal to this datetime
		object. If None (default), backfill all hours. If get_full_hour is
		False, only segments starting after start will be backfilled.
	stop -- Only backfill hours starting before or equal to this datetime
		object. If None (default), backfill all hours. If get_full_hour is
		False, only segments finishing before stop will be backfilled.
	hour_order -- If 'random', randomise the order of hours. If 'forward', sort
		the hours in ascending order. If 'reverse', sort the hours in descending		order. Otherwise, do not change the order of hours (default).
	segment_order -- If 'random', randomise the order of segments (default).
		If 'forward', sort the segment in ascending order. If 'reverse', sort
		the segments in descending order. Otherwise, do not change the order of
		segments.
	get_full_hour -- If True (default), get all segments in an hour. If False,
		use start and stop to limit which segments are backfilled.
	recent_cutoff -- Skip backfilling segments younger than this number of
		seconds to prioritise letting the downloader grab these segments."""

	logging.info('Starting backfilling from {}'.format(node))

	if hours is None:
		# gather all available hours from all variants and take the union
		hours = set().union(*[
			list_remote_hours(node, stream, variant)
			for variant in variants
		])
	elif is_iterable(hours):
		hours = list(hours) # coerce to list so it can be sorted
	else:
		n_hours = hours
		if n_hours < 1:
			raise ValueError('Number of hours has to be 1 or greater')
		now = datetime.datetime.utcnow()
		hours = [(now - i * datetime.timedelta(hours=1)).strftime(HOUR_FMT) for i in range(n_hours)]

	if start is not None:
		hours = [hour for hour in hours if hour >= start]
	if stop is not None:
		hours = [hour for hour in hours if hour <= stop]

	# useful if running in parallel so multiple nodes don't request the same hour at the same time
	if hour_order == 'random':
		random.shuffle(hours)
	elif hour_order == 'forward':
		hours.sort()
	elif hour_order == 'reverse':
		hours.sort(reverse=True)

	for variant in variants:

		for hour in hours:

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
					logging.warning('File {} invaid: {}'.format(path, e.value))
					continue
				
				if not get_full_hour and start is not None and segment['start'] < start:
					continue
				if not get_full_hour and start is not None and segment['end'] > stop:
					continue

				#to avoid getting in the downloader's way ignore segments less than recent_cutoff old
				if datetime.datetime.utcnow() - segment['start'] < datetime.timedelta(seconds=recent_cutoff):
					continue

				get_remote_segment(base_dir, node, stream, variant, hour, missing_segment)

	logging.info('Finished backfilling from {}'.format(node))

							
def main(base_dir, stream, variants, fill_wait=5, full_fill_wait=180, sleep_time=1):
	"""Prototype backfiller service.

	Do a backfill of the last 3 hours from stream/variants from all nodes initially before doing a full backfill from all nodes. Then every sleep_time minutes check to see if more than fill_wait minutes have passed since the last backfill. If so do a backfill of the last 3 hours. Also check whether it has been more than full_fill_wait minutes since the last full backfill; if so, do a full backfill."""
	# TODO replace this with a more robust event based service and backfill from multiple nodes in parallel
	# stretch goal: provide an interface to trigger backfills manually
	# stretch goal: use the backfiller to monitor the restreamer

	fill_start = datetime.datetime.now()
	full_fill_start = fill_start

	backfill(base_dir, stream, variants)
	backfill(base_dir, stream, variants, order='random')
	
	# I'm sure there is a module that does this in a more robust way 
	# but I understand this and it gives the behaviour I want
	while True:

		now = datetime.datetime.now()

		if now - full_fill_start > datetime.timedelta(minutes=full_fill_wait):

			backfill(base_dir, stream, variants)

			fill_start = now
			full_fill_start = fill_start

		elif now - fill_start > datetime.timedelta(minutes=fill_wait):

			backfill(base_dir, stream, variants, 3)

			fill_start = now

		else:
			time.sleep(common.jitter(60 * sleep_time))

