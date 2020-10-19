import errno
import datetime
import itertools
import logging
import os
import signal
import uuid

import argh
import gevent.backdoor
import matplotlib
import matplotlib.image
import numpy as np
import prometheus_client as prom

import common
from common import dateutil
from common import database


segment_count_gauge = prom.Gauge(
		'segment_count',
		'Number of segments in an hour',
		['channel', 'quality', 'hour', 'type'],
)

segment_duration_gauge = prom.Gauge(
		'segment_duration',
		'Segment duration in an hour',
		['channel', 'quality', 'hour', 'type'],
)

raw_coverage_gauge = prom.Gauge(
		'raw_coverage',
		'Total time covered by segments in an hour',
		['channel', 'quality', 'hour'],
)

editable_coverage_gauge = prom.Gauge(
		'editable_coverage',
		'Non-overlapping time covered by segments in an hour',
		['channel', 'quality', 'hour'],
)

raw_holes_gauge = prom.Gauge(
		'raw_holes',
		'Number of holes in raw coverage for the hour',
		['channel', 'quality', 'hour'],
)

editable_holes_gauge = prom.Gauge(
		'editable_holes',
		'Number of holes in editable coverage for the hour',
		['channel', 'quality', 'hour'],
)

overlap_count_gauge = prom.Gauge(
		'overlap_count',
		'Number of overlap segments for the hour',
		['channel', 'quality', 'hour', 'type'],
)

overlap_duration_gauge = prom.Gauge(
		'overlap_duration',
		'Duration of overlaping segments for the hour',
		['channel', 'quality', 'hour', 'type'],
)
 

HOUR_FMT = '%Y-%m-%dT%H'

class CoverageChecker(object):
	"""Checks the segment coverage for a given channel in a a given directoy."""

	CHECK_INTERVAL = 60 #seconds between checking coverage

	def __init__(self, channel, qualities, base_dir, first_hour, last_hour,
			make_page, connection_string):
		"""Constructor for CoverageChecker.

		Creates a checker for a given channel with specified qualities."""

		self.base_dir = base_dir
		self.channel = channel
		self.qualities = qualities
		self.first_hour = first_hour
		self.last_hour = last_hour
		self.make_page = make_page
		self.db_manager = None if connection_string is None else database.DBManager(dsn=connection_string)
		self.stopping = gevent.event.Event()
		self.logger = logging.getLogger('CoverageChecker({})'.format(channel))


	def stop(self):
		"""Stop checking coverage."""

		self.logger.info('Stopping')
		self.stopping.set()

	def create_coverage_map(self, quality, all_hour_holes, all_hour_partials,
			pixel_length=2, rows=300):
		"""Create a PNG image showing segment coverage.

		Each pixel repersents pixel_length seconds, with time increasing from
		top to bottom along each column then right to left. By default each
		pixel is 2 s and each column of the image repersents 10 min. White
		pixels have no coverage, orange pixels only have coverage by partial
		segments and blue pixels have coverage by full segments. If any part
		of a pixel does not have coverage, it is marked as not having coverage.
		Likewise, if only a partial segment is available for any part of a
		pixel, it is marked as partial.

		all_hour_holes -- a dict mapping hours to lists of holes
		all_hour_holes -- a dict mapping hours to lists of partial segments
		pixel_length -- length of a pixel in seconds
		rows -- the height of the image"""

		if not all_hour_holes:
			self.logger.info('No hours to generate coverage map from')
			return


		if self.first_hour is None:
			first_hour = datetime.datetime.strptime(min(all_hour_holes.keys()), HOUR_FMT)
		else:
			first_hour = self.first_hour.replace(minute=0, second=0, microsecond=0)
		if self.last_hour is None:
			last_hour = datetime.datetime.strptime(max(all_hour_holes.keys()), HOUR_FMT)
		else:
			last_hour = self.last_hour.replace(minute=0, second=0, microsecond=0)
		self.logger.info('Creating coverage map for {} from {} to {}'.format(quality,
			first_hour.strftime(HOUR_FMT), last_hour.strftime(HOUR_FMT)))

		hours = []
		latest_hour = first_hour
		while latest_hour <= last_hour:
			hours.append(latest_hour)
			latest_hour += datetime.timedelta(hours = 1)

		pixel_starts = np.arange(0, 3600, pixel_length) # start times of the pixels in an hour in seconds
		pixel_ends = np.arange(pixel_length, 3601, pixel_length) # end times of the pixels in an hour in seconds
		pixel_count = 3600 / pixel_length # number of pixels in an hour
		coverage_mask = np.zeros(len(hours) * pixel_count, dtype=np.bool_)
		partial_mask = np.zeros(len(hours) * pixel_count, dtype=np.bool_)
		for i, hour in enumerate(hours):
			hour_str = hour.strftime(HOUR_FMT)
			if hour_str in all_hour_holes:

				hour_coverage = np.ones(pixel_count, dtype=np.bool_)
				hour_partial = np.zeros(pixel_count, dtype=np.bool_)

				for hole in all_hour_holes[hour_str]:
					hole_start = np.floor((hole[0] - hour).total_seconds() / pixel_length) * pixel_length # the start of the pixel containing the start of the hole
					hole_end = np.ceil((hole[1] - hour).total_seconds() / pixel_length) * pixel_length # the end of the pixel containing the end of the hole
					hour_coverage = hour_coverage & ((pixel_starts < hole_start) | (pixel_ends > hole_end))

				for partial in all_hour_partials[hour_str]:
					partial_start = np.floor((partial[0] - hour).total_seconds() / pixel_length) * pixel_length  # the start of the pixel containing the start of the partial segment
					partial_end = np.ceil((partial[1] - hour).total_seconds() / pixel_length) * pixel_length # the end of the pixel containing the end of the partial segment
					hour_partial = hour_partial | ((pixel_starts >= partial_start) & (pixel_ends <= partial_end))

				coverage_mask[i * pixel_count:(i + 1) * pixel_count] = hour_coverage
				partial_mask[i * pixel_count:(i + 1) * pixel_count] = hour_partial

		# convert the flat masks into 2-D arrays
		columns = coverage_mask.size / rows
		coverage_mask = coverage_mask.reshape((columns, rows)).T
		partial_mask = partial_mask.reshape((columns, rows)).T
		
		# use the masks to set the actual pixel colours
		colours = np.ones((rows, columns, 3))
		colours[coverage_mask] = matplotlib.colors.to_rgb('tab:blue')
		colours[coverage_mask & partial_mask] = matplotlib.colors.to_rgb('tab:orange')
		# write the pixel array to a temporary file then atomically rename it
		path_prefix = os.path.join(self.base_dir, 'coverage-maps', '{}_{}'.format(self.channel, quality))
		temp_path = '{}_{}.png'.format(path_prefix, uuid.uuid4())
		final_path = '{}_coverage.png'.format(path_prefix)
		common.ensure_directory(temp_path)
		matplotlib.image.imsave(temp_path, colours)
		os.rename(temp_path, final_path)
		self.logger.info('Coverage map for {} created'.format(quality))

	def create_coverage_page(self, quality):
		nodes = {}
		try:
			connection = self.db_manager.get_conn()
			host = [s.split('=')[-1] for s in connection.dsn.split() if 'host' in s][0]
			self.logger.info('Fetching list of nodes from {}'.format(host))
			results = database.query(connection, """
				SELECT name, url
				FROM nodes
				WHERE backfill_from""")
			for row in results:
				nodes[row.name] = row.url
		except:
			self.logger.exception('Getting nodes failed.', exc_info=True)
			return

		self.logger.info('Nodes fetched: {}'.format(nodes.keys()))

		html = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="30"/>
    <title>{0} {1} Segment Coverage Maps</title>
      <style>
        html {{ background-color: #222;}}
        h1   {{ color: #eee;
               text-align: center;
               font-family: sans-serif;}}
        h3   {{ color: #eee;
               text-align: center;
               font-family: sans-serif;}}
       img  {{ display: block;
              margin-left: auto;
              margin-right: auto;}}
    </style>
  </head>
  <body>
    <h1>{0} {1}</h1>""".format(self.channel, quality)

		for node in sorted(nodes.keys()):
			html += """    <h3>{}</h3>
	<img src="{}/segments/coverage-maps/{}_{}_coverage.png" alt="{}">
""".format(node, nodes[node], self.channel, quality, node)
	
		html += """  </body>
</html>"""

		path_prefix = os.path.join(self.base_dir, 'coverage-maps', '{}_{}'.format(self.channel, quality))
		temp_path = '{}_{}.html'.format(path_prefix, uuid.uuid4())
		final_path = '{}_coverage.html'.format(path_prefix)
		common.ensure_directory(temp_path)
		with open(temp_path, 'w') as f:
			f.write(html)
		os.rename(temp_path, final_path)
		self.logger.info('Coverage page for {} created'.format(quality))


	def run(self):
		"""Loop over available hours for each quality, checking segment coverage."""
		self.logger.info('Starting')

		while not self.stopping.is_set():

			for quality in self.qualities:
				if self.stopping.is_set():
					break

				path = os.path.join(self.base_dir, self.channel, quality)
				try:
					hours = [name for name in os.listdir(path) if not name.startswith('.')]
				except OSError as e:
					if e.errno == errno.ENOENT:
						self.logger.info('{} does not exist, skipping'.format(path))
						continue

				hours.sort()
				previous_hour_segments = None
				all_hour_holes = {}
				all_hour_partials = {}
				for hour in hours:
					if self.stopping.is_set():
						break
					self.logger.info('Checking {}/{}'.format(quality, hour))

					# based on common.segments.best_segments_by_start
					# but more complicated to capture more detailed metrics
					hour_path = os.path.join(self.base_dir, self.channel, quality, hour)
					try:
						segment_names = [name for name in os.listdir(hour_path) if not name.startswith('.')]
					except OSError as e:
						if e.errno == errno.ENOENT:
							self.logger.warning('Hour {} was deleted between finding it and processing it, ignoring'.format(hour))
							continue 
					segment_names.sort()
					parsed = []
					bad_segment_count = 0
					for name in segment_names:
						try:
							parsed.append(common.parse_segment_path(os.path.join(hour_path, name)))
						except ValueError:
							self.logger.warning("Failed to parse segment: {!r}".format(os.path.join(hour_path, name)), exc_info=True)
							bad_segment_count += 1

					full_segment_count = 0
					suspect_segment_count = 0
					partial_segment_count = 0
					full_segment_duration = datetime.timedelta()
					suspect_segment_duration = datetime.timedelta()
					partial_segment_duration = datetime.timedelta()
					full_overlaps = 0
					full_overlap_duration = datetime.timedelta()
					suspect_overlaps = 0
					suspect_overlap_duration = datetime.timedelta()	
					partial_overlaps = 0
					partial_overlap_duration = datetime.timedelta()
					best_segments = []
					holes = []
					editable_holes = []
					previous = None
					previous_editable = None
					coverage = datetime.timedelta()
					editable_coverage = datetime.timedelta()
					only_partials = []

					# loop over all start times
					# first select the best segment for a start time
					# then update coverage
					for start_time, segments in itertools.groupby(parsed, key=lambda segment: segment.start):
						full_segments = []
						suspect_segments = []
						partial_segments = []
						for segment in segments:
							if segment.type == 'full':
								full_segments.append(segment)
								full_segment_count += 1
								full_segment_duration += segment.duration
							elif segment.type == 'suspect':
								suspect_segments.append(segment)
								suspect_segment_count += 1
								suspect_segment_duration += segment.duration	
							elif segment.type == 'partial':
								partial_segments.append(segment)
								partial_segment_count += 1
								partial_segment_duration += segment.duration
						if full_segments:
							full_segments.sort(key=lambda segment: (segment.duration))
							best_segment = full_segments[-1]
							for segment in full_segments[:-1]:
								full_overlaps += 1
								full_overlap_duration += segment.duration
							for segment in partial_segments:
								partial_overlaps += 1
								partial_overlap_duration += segment.duration
						elif suspect_segments:
							suspect_segments.sort(key=lambda segment: os.stat(segment.path).st_size)
							best_segment = suspect_segments[-1]
							only_partials.append((best_segment.start, best_segment.start + best_segment.duration))
							for segment in suspect_segments[:-1]:
								suspect_overlaps += 1
								suspect_overlap_duration += segment.duration

						elif partial_segments:
							partial_segments.sort(key=lambda segment: os.stat(segment.path).st_size)
							best_segment = partial_segments[-1]
							only_partials.append((best_segment.start, best_segment.start + best_segment.duration))
							for segment in partial_segments[:-1]:
								partial_overlaps += 1
								partial_overlap_duration += segment.duration
						else:
							# ignore any start times with only temporary segments
							continue
						self.logger.debug(best_segment.path.split('/')[-1])
						best_segments.append(best_segment)

						# now update coverage, overlaps and holes
						if previous is None:
							coverage += best_segment.duration
							editable_coverage += best_segment.duration
							previous_editable = best_segment
						else:
							previous_end = previous.start + previous.duration
							if segment.start < previous_end:
								if segment.type == 'full':
									full_overlaps += 1
									full_overlap_duration += previous_end - segment.start
								elif segment.type == 'suspect':
									suspect_overlaps += 1
									suspect_overlap_duration += previous_end - segment.start
								else:
									partial_overlaps += 1
									partial_overlap_duration += previous_end - segment.start
								coverage += segment.start - previous_end + segment.duration
							else:
								coverage += segment.duration
								editable_coverage += segment.duration

								if segment.start > previous_end:
									holes.append((previous_end, segment.start))

								previous_editable_end = previous_editable.start + previous_editable.duration
								if segment.start > previous_editable_end:
									editable_holes.append((previous_editable_end, segment.start))

								previous_editable = best_segment

						previous = best_segment

					if best_segments:	
						start = best_segments[0].start
						end = best_segments[-1].start + best_segments[-1].duration
						hole_duration = end - start - coverage
						editable_hole_duration = end - start - editable_coverage
	
						hour_start = datetime.datetime.strptime(hour, HOUR_FMT)
						hour_end = hour_start + datetime.timedelta(hours=1)
						# handle the case when there is a hole between the last segment of the previous hour and the first of this
						if previous_hour_segments:
							last_segment = previous_hour_segments[-1]
							if best_segments[0].start > last_segment.start + last_segment.duration:
								holes.append((hour_start, start))
								hole_duration += start - hour_start
								editable_holes.append((hour_start, start))
								editable_hole_duration += start - hour_start
	
						# handle the case when there is a hole between the last segment and the end of the hour if not the last hour
						if hour != hours[-1] and end < hour_end:
							holes.append((end, hour_end))
							hole_duration += hour_end - end
							editable_holes.append((end, hour_end))
							editable_hole_duration += hour_end - end

					# update the large number of Prometheus guages
					segment_count_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='full'
							).set(full_segment_count)
					segment_count_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='suspect'
							).set(suspect_segment_count)					
					segment_count_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='partial'
							).set(partial_segment_count)
					segment_count_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='bad'
							).set(bad_segment_count)
					segment_duration_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='full'
							).set(full_segment_duration.total_seconds())
					segment_duration_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='suspect'
							).set(suspect_segment_duration.total_seconds())
					segment_duration_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='partial'
							).set(partial_segment_duration.total_seconds())
					raw_coverage_gauge.labels(
							channel=self.channel, quality=quality, hour=hour
							).set(coverage.total_seconds())
					editable_coverage_gauge.labels(
							channel=self.channel, quality=quality, hour=hour
							).set(editable_coverage.total_seconds())
					raw_holes_gauge.labels(
							channel=self.channel, quality=quality, hour=hour
							).set(len(holes))
					editable_holes_gauge.labels(
							channel=self.channel, quality=quality, hour=hour
							).set(len(editable_holes))
					overlap_count_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='full'
							).set(full_overlaps)
					overlap_count_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='suspect'
							).set(suspect_overlaps)					
					overlap_count_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='partial'
							).set(partial_overlaps)
					overlap_duration_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='full'
							).set(full_overlap_duration.total_seconds())
					overlap_duration_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='suspect'
							).set(suspect_overlap_duration.total_seconds())
					overlap_duration_gauge.labels(
							channel=self.channel, quality=quality, hour=hour, type='partial'
							).set(partial_overlap_duration.total_seconds())

					# log the same information
					if best_segments:
						self.logger.info('{}/{}: Start: {} End: {} ({} s)'.format(
							quality, hour, start, end,
							(end - start).total_seconds()))
						self.logger.info('{}/{}: {} full segments totalling {} s'.format(
							quality, hour, full_segment_count,
							full_segment_duration.total_seconds()))
						self.logger.info('{}/{}: {} bad segments'.format(
							quality, hour, bad_segment_count))
						self.logger.info('{}/{}: {} overlapping full segments totalling {} s'.format(
							quality, hour, full_overlaps,
							full_overlap_duration.total_seconds()))
						self.logger.info('{}/{}: {} suspect segments totalling {} s'.format(
							quality, hour, suspect_segment_count,
							suspect_segment_duration.total_seconds()))
						self.logger.info('{}/{}: {} overlapping suspect segments totalling {} s'.format(
							quality, hour, suspect_overlaps,
							suspect_overlap_duration.total_seconds()))	
						self.logger.info('{}/{}: {} partial segments totalling {} s'.format(
							quality, hour, partial_segment_count,
							partial_segment_duration.total_seconds()))
						self.logger.info('{}/{}: {} overlapping partial segments totalling {} s'.format(
							quality, hour, partial_overlaps,
							partial_overlap_duration.total_seconds()))
						self.logger.info('{}/{}: raw coverage {} s, editable coverage {} s '.format(
							quality, hour, coverage.total_seconds(),
							editable_coverage.total_seconds()))
						self.logger.info('{}/{}: {} holes totalling {} s '.format(
							quality, hour, len(holes),
							hole_duration.total_seconds()))
						self.logger.info('{}/{}: {} editable holes totalling {} s '.format(
							quality, hour, len(editable_holes),
							editable_hole_duration.total_seconds()))
						self.logger.info('Checking {}/{} complete'.format(
							quality, hour))
	
						# add holes for the start and end hours for the
						# coverage map. do this after updating gauges and
						# logging as these aren't likely real holes, just the
						# start and end of the stream.
						if previous_hour_segments is None:
							holes.append((hour_start, start))
						if hour == hours[-1]:
							holes.append((end, hour_end))
	
	
						all_hour_holes[hour] = holes
						all_hour_partials[hour] = only_partials					
	
						previous_hour_segments = best_segments

					else:
						self.logger.info('{}/{} is empty'.format(quality, hour))

				self.create_coverage_map(quality, all_hour_holes, all_hour_partials)
				if self.make_page:
					self.create_coverage_page(quality)

			self.stopping.wait(common.jitter(self.CHECK_INTERVAL))


@argh.arg('channels', nargs='*', help='Channels to check coverage of')
@argh.arg('--base-dir', help='Directory where segments are stored. Default is current working directory.')
@argh.arg('--qualities', help="Qualities of each channel to checked. Comma seperated if multiple. Default is 'source'.")
@argh.arg('--first-hour', help='First hour to compute coverage for. Default is earliest available hour.')
@argh.arg('--last-hour', help='Last hour to compute coverage for. Default is lastest available hour.')
@argh.arg('--make-page', help='Make a html page displaying coverage maps for all nodes in database')
@argh.arg('--connection-string', help='Postgres connection string, which is either a space-separated list of key=value pairs, or a URI like: postgresql://USER:PASSWORD@HOST/DBNAME?KEY=VALUE')
@argh.arg('--metrics-port', help='Port for Prometheus stats. Default is 8006.')
@argh.arg('--backdoor-port', help='Port for gevent.backdoor access. By default disabled.')
def main(channels, base_dir='.', qualities='source', first_hour=None,
		last_hour=None, make_page=False, connection_string=None,
		metrics_port=8006, backdoor_port=0):
	"""Segment coverage service"""

	qualities = qualities.split(',') if qualities else []
	qualities = [quality.strip() for quality in qualities]
	if first_hour is not None:
		first_hour = dateutil.parse(first_hour)
	if last_hour is not None:
		last_hour = dateutil.parse(last_hour)

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	managers = []
	workers = []
	for channel in channels:
		logging.info('Starting coverage checks {} with {} as qualities in {}'.format(channel, ', '.join(qualities), base_dir))
		manager = CoverageChecker(channel, qualities, base_dir, first_hour,
				last_hour, make_page, connection_string)
		managers.append(manager)
		workers.append(gevent.spawn(manager.run))

	def stop():
		for manager in managers:
			manager.stop()

	gevent.signal_handler(signal.SIGTERM, stop)

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
	#	failed, we report one arbitrarily.
	for worker in workers:
		worker.get()

	logging.info('Gracefully stopped')		
