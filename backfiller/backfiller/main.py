"""Download segments from other nodes to catch stuff this node missed."""
# TODO logging, better exception handling

import datetime
import errno
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
	resp = requests.get(uri, timeout=timeout)
	return resp.json()


def list_remote_segments(node, stream, variant, hour, timeout=TIMEOUT):
	"""Wrapper around a call to restreamer.list_segments."""
	uri = '{}/files/{}/{}/{}'.format(node, stream, variant, hour)
	resp = requests.get(uri, timeout=timeout)
	return resp.json()


def get_remote_segment(base_dir, node, stream, variant, hour, missing_segment,
			timeout=TIMEOUT):
	"""Get a segment from a node.

	Fetches stream/variant/hour/missing_segment from node and puts it in base_dir/stream/variant/hour/missing_segment. If the segment already exists locally, this does not attempt to fetch it."""

	path = os.path.join(base_dir, stream, variant, hour, missing_segment)
	# check to see if file already exists to avoid unnecessarily copying it
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
		except Exception as e:
			print node, e


def is_iterable(x):
	"""Test whether input is iterable."""
	try:
 		iter(x)
	except TypeError:
		return False
	return True


def backfill_node(base_dir, node, stream, variants, hours=None, start=None,
		stop=None, order=None, recent_cutoff=60):
	"""Backfill from remote node.

	Backfill from node/stream/variants to base_dir/stream/variants.

	Keyword arguments:
	hours -- If None (default), backfill all available hours. If iterable, backfill only hours in iterable. Otherwise backfill the last N hours, starting with the lastest.
	start -- Only backfill hours starting after or equal to this datetime object. If None (default), backfill all hours.
	stop -- Only backfill hours starting before or equal to this datetime object. If None (default), backfill all hours.
	order -- If 'random', randomise the order of hours. If 'forward', sort the hours in acceding order. If 'reverse', sort the hours in descending order. Otherwise, do not change the order of hours (default).
	recent_cutoff -- Skip backfilling segments younger than this number of seconds to prioritise letting the downloader grab these segments."""

	if hours is None:
		hours = list_remote_hours(node, stream, variant)
	elif is_iterable(hours):
		None
	else:
		n_hours = hours
		if n_hours < 1:
			raise ValueError('Number of hours has to be 1 or greater')
		now = datetime.datetime.utcnow()
		hours = [(now - i * timedelta(hours=1)).strftime(HOUR_FMT) for i in range(n_hours)]

	if start is not None:
		hours = [hour for hour in hours if hour >= start]
	if stop is not None:
		hours = [hour for hour in hours if hour <= stop]

	# useful if running in parallel and expecting to fetch a segments from
	# multiple hours (say on start up) so that you don't try to backfill the
	# same hour at the same time 
	if order == 'random':
		hours = random.shuffle(hours)
	elif order == 'forward':
		sort(hours)
	elif order == 'reverse':
		sort(hours, reverse=True)

	for variant in variants:

		for hour in hours:

			local_segments = set(list_local_segments(base_dir, stream, variant, hour))
			remote_segments = set(list_remote_segments(node, stream, variant, hour))
			missing_segments = remote_segments - local_segments

			for missing_segment in missing_segments:

				#ignore temporary files
				if 'temp' in missing_segment:
					continue

				#only get '*.ts' files to try to only get segments
				if missing_segment[-3:] != '.ts':
					continue

				#to avoid getting in the downloader's way ignore segments less than recent_cutoff old
				time_str = '{}:{}'.format(hour, missing_segment.split('-')[0])
				segment_time = datetime.datetime.strptime(time_str, HOUR_FMT + ':%M:%S.%f')
				if datetime.datetime.utcnow() - segment_time < datetime.timedelta(seconds=recent_cutoff):
					continue

				get_remote_segment(base_dir, node, stream, variant, hour, missing_segment)

							
def main(base_dir, stream, variants, fill_wait=5, full_fill_wait=180, sleep_time=1):
	"""Prototype backfiller service.

	Do a full backfill of stream/variants from all nodes initially. Then every sleep_time minutes check to see if more than fill_wait minutes have passed since the last backfill. If so do a backfill of the last 3 hours. Also check whether it has been more than full_fill_wait minutes since the last full backfill; if so, do a full backfill."""
	# TODO replace this with a more robust event based service and backfill from multiple nodes in parallel
	# stretch goal: provide an interface to trigger backfills manually
	# stretch goal: use the backfiller to monitor the restreamer

	fill_start = datetime.datetime.now()
	full_fill_start = fill_start

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

