
# this is a prototype of the backfiller
# lots about web services and the like I don't know
# needs logging, exception handling and the like
# also proper doc strings

# when starting the backfiller and every few hours, backfill everything
# more frequently, backfill the last couple hours
# (last three hour directories so always at least two hours).

import os
import time
import datetime

import requests

hour_fmt = '%Y-%m-%dT%H'


def get_nodes():

	# either read a config file or query the database to get the addresses
	# of the other nodes
	# figure out some way that the local machine isn't in the list of returned
	# nodes so that 

	# as a prototype can just hardcode some addresses.

	nodes = []

	return nodes

def list_local_segments(base_dir, stream, variant, hour):

	# based on restreamer.list_segments
	# could just call restreamer.list_segments but this avoids http/json
	# overheads
	path = os.path.join(base_dir, stream, variant, hour)
	local_segments = [name for name in os.listdir(path) if not
						name.startswith('.')]
	return local_segments

def list_remote_hours(node, stream, variant):

	# just a wrapper around a call to restreamer.list_hours
	# TODO if the call fails, log it and just return an empty list

	resp = requests.get('https://{}/files/{}/{}'.format(node, stream, variant))
	hours = resp.json()

	return hours

def list_remote_segments(node, stream, variant, hour):

	# just a wrapper around a call to restreamer.list_segments
	# TODO if the call fails, log it and just return an empty list

	resp = requests.get('https://{}/files/{}/{}/{}'.format(node, stream,
						variant, hour_str))
	remote_segments = resp.json()
	return remote_segments

# based on _get_segment in downloader/main
# very basic error handling
def get_remote_segment(base_dir, node, stream, variant, hour, missing_segment):

	resp = requests.get('https://{}/segments/{}/{}/{}/{}'.format(node, stream,
						variant, hour, missing_segment), stream=True)

	if resp.status_code != 200:
		return False

	temp_name = 'temp_backfill'

	with open(temp_name, 'w') as f:
		for chunk in resp.iter_content(8192):
			f.write(chunk)

	dir_path = os.path.join(base_dir, stream, variant, hour)

	if not os.path.exists(dir_path):
		try:
			os.mkdir(dir_path)
		except OSError as e:
			# Ignore if EEXISTS. This is needed to avoid a race if two getters run at once.
			if e.errno != errno.EEXIST:
				raise

	path = os.path.join(dir_path, missing_segment)
	os.rename(temp_name, path)

	return True



def backfill(base_dir, stream, variants, hours=None, nodes=None,
	failure_limit=5):

	# if hours is int, backfill last hours hourdirs
	# else if hours is None, backfill all hourdirs
	# else assume hours is iterable and backfill those hourdirs
	
	# loop over nodes asking for a list of segments then downloads any 
	# segments it doesn't have

	if nodes is None:
		nodes = get_nodes()

	if isinstance(hours, int):
		n_hours = hours

		if n_hours < 1:
			raise ValueError('Number of hours has to be 1 or greater')

		now = datetime.datetime.utcnow()
		
		now_str = now.strftime(hour_fmt)
		now_hour = datetime.strptime(now_str, hour_fmt)

		hours = [now_str]

		for i in range(n_hours - 1):

			previous_hour =  datetime.strptime(hours[-1], hour_fmt)
			current_hour = previous_hour + datetime.timedelta(hours=-1)
			hours.append(current_hour.strftime(hour_fmt))

	for node in nodes:

		backfill_node(base_dir, node, stream, variants, hours,
			failure_limit)


def backfill_node(base_dir, node, stream, variants, hours, failure_limit):

	# split into its own function to allow breaking out of two loops at once
	# count failures this node has and if too many occur, assume node isn't
	# working and move onto next

	failures = 0
	for variant in variants:

		if hours is None:
			# if this fails, get an empty list back so function quickly
			# finishes
			node_hours = list_remote_hours(node, stream, variant)
		else:
			node_hours = hours

		for hour in node_hours:
			# if this fails, get an empty list back so this loop quickly
			# finishes			
			local_segments = list_local_segments(base_dir, stream, variant,
								hour)
			local_segments = set(local_segments)
			#should include the result of this in the failure count
			remote_segments = list_remote_segments(node, stream, variant, hour)
			remote_segments = set(remote_segments)
			missing_segments = remote_segments - local_segments

			for missing_segment in missing_segments:

				status = get_remote_segment(base_dir, node, stream, variant,
							hour, missing_segment)

				if not status:
					failures += 1

				if failures > failure_limit:
					return
							
# all wait times are in minutes
# obviously adjust default times in response to how long back filling actually
# takes
def main(base_dir, stream, variants, fill_wait=5, full_fill_wait=180,
		sleep_time=1):

	fill_start = datetime.datetime.now()
	full_fill_start = fill_start

	# Do a full backfill at start
	backfill(base_dir, stream, variants)
	
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
			time.sleep(60 * sleep_time)


	



	


