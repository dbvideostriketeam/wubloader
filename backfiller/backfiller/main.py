
# this is a prototype of the backfiller
# lots about web services and the like I don't know
# needs logging, exception handling and the like
# also proper doc strings

# when starting the backfiller and every few hours, backfill everything
# more frequently, backfill the last couple hours
# (last three hour directories so always at least two hours).

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

	# either read a config file or query the database to get the addresses
	# of the other nodes
	# figure out some way that the local machine isn't in the list of returned
	# nodes so that 

	# as a prototype can just hardcode some addresses.
	# each element in nodes is a 'protocol://host:port/' string

	nodes = []
	return nodes


def list_local_segments(base_dir, stream, variant, hour):
	# based on restreamer.list_segments
	# could just call restreamer.list_segments but this avoids http/json overheads
	path = os.path.join(base_dir, stream, variant, hour)
	try:
		return [name for name in os.listdir(path) if not name.startswith('.')]

	except OSError as e:
		if e.errno != errno.ENOENT:
			raise
		return []	


def list_remote_hours(node, stream, variant, timeout=TIMEOUT):
	# just a wrapper around a call to restreamer.list_hours
	uri = '{}/files/{}/{}'.format(node, stream, variant)
	resp = requests.get(uri, timeout=timeout)
	return resp.json()


def list_remote_segments(node, stream, variant, hour, timeout=TIMEOUT):
	# just a wrapper around a call to restreamer.list_segments
	uri = '{}/files/{}/{}/{}'.format(node, stream, variant, hour)
	resp = requests.get(uri, timeout=timeout)
	return resp.json()


# based on _get_segment in downloader/main
# very basic error handling
def get_remote_segment(base_dir, node, stream, variant, hour, missing_segment,
			timeout=TIMEOUT):

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

	except Exception:
		if os.path.exists(temp_path):
			os.remove(temp_path)
		raise

	common.rename(temp_path, path)



def backfill(base_dir, stream, variants, hours=None, nodes=None, start=None,
		 stop=None, order=None):
	
	# loop over nodes backfilling from each

	if nodes is None:
		nodes = get_nodes()

	#ideally do this in parallel
	for node in nodes:
		try:
			backfill_node(base_dir, node, stream, variants, hours, start, stop, order=order)
		#need to replace this with a more sophisticated error handler
		except Exception as e:
			print node, e


def is_iterable(x):
	try:
 		iter(x)
	except TypeError:
		return False
	return True


def backfill_node(base_dir, node, stream, variants, hours=None, start=None,
		stop=None, recent_cutoff=60, order=None):

	# if hours is None, backfill all hourdirs
	if hours is None:
		hours = list_remote_hours(node, stream, variant)
	# if hours is iterable, backfill those hourdirs
	elif is_iterable(hours):
		None
	# assume int and backfill last hours hourdirs
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

	for variant in variants:

		for hour in hours:

			local_segments = set(list_local_segments(base_dir, stream, variant, hour))
			remote_segments = set(list_remote_segments(node, stream, variant, hour))
			missing_segments = remote_segments - local_segments

			for missing_segment in missing_segments:

				#ignore temporary files
				if 'temp' in missing_segment:
					continue

				#to avoid getting in the downloader's way ignore segments less than recent_cutoff old
				time_str = '{}:{}'.format(hour, missing_segment.split('-')[0])
				segment_time = datetime.datetime.strptime(time_str, HOUR_FMT + ':%M:%S.%f')
				if datetime.datetime.utcnow() - segment_time < datetime.timedelta(seconds=recent_cutoff):
					continue

				get_remote_segment(base_dir, node, stream, variant, hour, missing_segment)

							
# all wait times are in minutes
# obviously adjust default times in response to how long back filling actually
# takes
def main(base_dir, stream, variants, fill_wait=5, full_fill_wait=180, sleep_time=1):

	fill_start = datetime.datetime.now()
	full_fill_start = fill_start

	# Do a full backfill at start
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

