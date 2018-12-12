
# this is a prototype of the backfiller
# lots about web services and the like I don't know
# needs logging, exception handling and the like

import glob
import requests
import os


def get_nodes():

    # either read a config file or query the database to get the addresses of
    # the other nodes

    # as a prototype can just hardcode some addresses.

    nodes = []

    return nodes

def list_remote_segments(node):

    # return a list of paths
    # obviously update path with real one

    resp = requests.get(node + '/wubloader/segment_list')
    remote_segments = resp.json() #replace with appropriate parser

    return remote_segments

#based on _get_segment in downloader/main
#should have a more general shared version of this
def get_remote_segment(node, segment):

    # obviously update path with real one
    resp = requests.get(node + '/wubloader/segments/' + segment, stream=True)

    with open('temp_backfill', 'w') as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)

    os.rename(temp, segment)



def back_fill(base_dir, nodes=None):

    # loop over nodes asking for a list of segments then downloads any segments
    # it doesn't have

    if nodes is None:
        nodes = get_nodes()


    for node in nodes:

        # need to figure out how to properly check whether this node is the
        # same
        if node == 'localhost':
            continue

        # not sure how much we want to hard code the search
        local_segments = set(glob.glob(base_dir + '/*/*/*.ts'))

        remote_segments = set(list_remote_segments(node))

        missing_segments = remote_segments - local_segments

        
        for missing_segment in missing_segments:
            get_remote_segment(node, missing_segment)



def main(base_dir, wait_time=60):

    None
    # every wait_time call back_fill
    # time from start of back_fill
    # to keep things simple don't try two back_fills at the same time
    # wait for previous one to start before launching second.
    # if it's taken more than wait_time for back_fill to run, start immediately
