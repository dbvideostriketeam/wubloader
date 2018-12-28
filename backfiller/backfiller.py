
# this is a prototype of the backfiller
# lots about web services and the like I don't know
# needs logging, exception handling and the like

# when starting the backfiller and every few hours, backfill everything
# more frequently, backfill the last couple hours
# (last three hour directories so always at least two hours).

import requests
import os

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

	path = os.path.join(base_dir, stream, variant, hour)
	local_segments = [name for name in os.listdir(path) if not
						name.startswith('.')]
	return local_segments

def get_hours(node, stream, variant):

	resp = requests.get('https://{}/files/{}/{}'.format(node, stream, variant))
	hours = resp.json()

	return hours

def list_remote_segments(node, stream, variant, hour):

	resp = requests.get('https://{}/files/{}/{}/{}'.format(node, stream,
						variant, hour_str))
	remote_segments = resp.json() #replace with appropriate parser

	return remote_segments

#based on _get_segment in downloader/main
def get_remote_segment(base_dir, node, stream, variant, hour, missing_segment):

	resp = requests.get('https://{}/segments/{}/{}/{}/{}'.format(node, stream,
						variant, hour, missing_segment), stream=True)

	if resp.status_code != 200:
		return False

	temp_name = 'temp_backfill'

	with open(temp_name, 'w') as f:
		for chunk in resp.iter_content(8192):
			f.write(chunk)

	path = os.path.join(base_dir, stream, variant, hour, missing_segment)
	os.rename(temp_name, segment)

	return True


def back_fill(static_folder, stream, variants, hours=None, nodes=None,
	failure_limit=5):

	# if variants is None, backfill all versions
	# if hours is None, backfill all hourdirs
	# if hours is iterable, backfill those hourdirs
	# if hours is int, backfill last hours hourdirs
	
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

		back_fill_node(static_folder, node, stream, variants, hours,
			failure_limit)


def back_fill_node(base_dir, node, stream, variants, hours, failure_limit):

	# need to figure out how to properly check whether this node is the same
	if is_local_host(node):
		return

	failures = 0
	for variant in variants:

		if hours is None:
			node_hours = get_hours(node, stream, variant)
		else:
			node_hours = hours

		for hour in node_hours:
			
			local_segments = list_local_segments(base_dir, stream, variant,
								hour)
			local_segments = set(local_segments)
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
							

def main(base_dir, wait_time=60):

	None
	# every wait_time call back_fill
	# time from start of back_fill
	# to keep things simple don't try two back_fills at the same time
	# wait for previous one to start before launching second.
	# if it's taken more than wait_time for back_fill to run, start
	# immediately
