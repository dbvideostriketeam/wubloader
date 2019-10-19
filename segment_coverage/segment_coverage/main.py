import datetime
import itertools
import logging
import os
import random
import signal

import argh
import gevent.backdoor
import matplotlib
import matplotlib.image
import numpy as np
import prometheus_client as prom

import common


full_segment_count_gauge = prom.Gauge(
		'full_segment_count',
		'Number of full segments in an hour',
		['channel', 'quality', 'hour'],
)

partial_segment_count_gauge = prom.Gauge(
		'partial_segment_count',
		'Number of partial segments in an hour',
		['channel', 'quality', 'hour'],
)

bad_segment_count_gauge = prom.Gauge(
		'bad_segment_count',
		'Number of segments that fail to parse in an hour',
		['channel', 'quality', 'hour'],
)

full_segment_duration_gauge = prom.Gauge(
		'full_segment_duration',
		'Full segment duration in an hour',
		['channel', 'quality', 'hour'],
)

partial_segment_duration_gauge = prom.Gauge(
		'partial_segment_duration',
		'Partial segment duration in an hour',
		['channel', 'quality', 'hour'],
)

raw_coverage_gauge = prom.Gauge(
		'raw_coverage',
		'Raw coverage for the hour',
		['channel', 'quality', 'hour'],
)

editable_coverage_gauge = prom.Gauge(
		'editable_coverage',
		'Editable coverage for the hour',
		['channel', 'quality', 'hour'],
)

raw_holes_gauge = prom.Gauge(
		'raw_holes',
		'Number of holes in raw coverage for the hour',
		['channel', 'quality', 'hour'],
)

editable_holes_gauge = prom.Gauge(
		'editable_hole',
		'Number of holes in editable coverage for the hour',
		['channel', 'quality', 'hour'],
)

full_overlap_count_gauge = prom.Gauge(
		'full_overlap_count',
		'Number of overlap full segments for the hour',
		['channel', 'quality', 'hour'],
)

partial_overlap_count_gauge = prom.Gauge(
		'partial_overlap_count',
		'Number of overlap partial segments for the hour',
		['channel', 'quality', 'hour'],
)

full_overlap_duration_gauge = prom.Gauge(
		'full_overlap_duration',
		'Duration of overlaping full segments for the hour',
		['channel', 'quality', 'hour'],
)

partial_overlap_duration_gauge = prom.Gauge(
		'partial_overlap_duration',
		'Duration of overlaping partial segments for the hour',
		['channel', 'quality', 'hour'],
)
 

HOUR_FMT = '%Y-%m-%dT%H'

class CoverageChecker(object):
	"""Checks the segment coverage for a given channel in a a given directoy."""

	CHECK_INTERVAL = 60 #seconds between checking coverage

	def __init__(self, channel, qualities, base_dir):
		"""Constructor for CoverageChecker.

		Creates a checker for a given channel with specified qualities."""
		self.base_dir = base_dir
		self.channel = channel
		self.qualities = qualities
		self.stopping = gevent.event.Event()
		self.logger = logging.getLogger('CoverageChecker({})'.format(channel))


	def stop(self):
		"""Stop checking coverage."""
		self.logger.info('Stopping')
		self.stopping.set()

	def create_coverage_map(self, quality, all_hour_holes, all_hour_partials,
			pixel_length=2, hour_count=168):
		"""Create a PNG show segment coverage.

		If any part of a pixel does not have coverage, it is marked as not
		having coverage. Likewise, if only a partial segment is available for
		any part of a pixel, it is marked as partial.

		all_hour_holes -- a dict mapping hours to lists of holes
		all_hour_holes -- a dict mapping hours to lists of partial segments
		pixel_length -- length of a pixel in seconds
		hour_count -- number of hours to create the map for"""

		self.logger.info('Creating coverage map for {}'.format(quality))

		latest_hour = datetime.datetime.strptime(max(all_hour_holes.keys()), HOUR_FMT)
		hours = [latest_hour - datetime.timedelta(hours=i) for i in range(hour_count - 1, -1, -1)]

		pixel_starts = np.arange(0, 3600, pixel_length) # starts of the pixels in 
		pixel_ends = np.arange(pixel_length, 3601, pixel_length)

		pixel_count = 3600 / pixel_length # number of pixels in an hour
		coverage_mask = np.zeros(hour_count * pixel_count, dtype=np.bool_)
		partial_mask = np.zeros(hour_count * pixel_count, dtype=np.bool_)
		for i in range(len(hours)):
			hour = hours[i]
			hour_str = hour.strftime(HOUR_FMT)
			if hour_str in all_hour_holes:

				hour_coverage = np.ones(pixel_count, dtype=np.bool_)
				hour_partial = np.zeros(pixel_count, dtype=np.bool_)

				for hole in all_hour_holes[hour_str]:
					hole_start = np.floor((hole[0] - hour).total_seconds() / pixel_length) * pixel_length # the start of the pixel containing the start of the hole
					hole_end = np.ceil((hole[1] - hour).total_seconds() / pixel_length) * pixel_length # the end of the pixel containing the end of the hole
					hour_coverage = hour_coverage & ((pixel_starts < hole_start) | (pixel_ends > hole_end))

				for partial in all_hour_partials[hour_str]:
					partial_start = np.floor((partial[0] - hour).total_seconds() / pixel_length) * pixel_length
					partial_end = np.ceil((partial[1] - hour).total_seconds() / pixel_length) * pixel_length
					hour_partial = hour_partial | ((pixel_starts >= partial_start) & (pixel_ends <= partial_end))

				coverage_mask[i * pixel_count:(i + 1) * pixel_count] = hour_coverage
				partial_mask[i * pixel_count:(i + 1) * pixel_count] = hour_partial

		rows = 300
		columns = coverage_mask.size / rows
		
		coverage_mask = coverage_mask.reshape((columns, rows)).T
		partial_mask = partial_mask.reshape((columns, rows)).T
		
		colours = np.ones((rows, columns, 3))
		colours[coverage_mask] = matplotlib.colors.to_rgb('tab:blue')
		colours[coverage_mask & partial_mask] = matplotlib.colors.to_rgb('tab:orange')
		
		final_path = os.path.join(self.base_dir, 'coverage-maps', '{}_{}_coverage.png'.format(self.channel, quality))
		temp_path = final_path.replace('_coverage', '_{}'.format(random.getrandbits(32)))
		common.ensure_directory(temp_path)
		matplotlib.image.imsave(temp_path, colours)
		os.rename(temp_path, final_path)
		self.logger.info('Coverage map for {} created'.format(quality))

	def run(self):
		"""Loop over available hours for each quality, checking segment coverage."""
		self.logger.info('Starting')

		while not self.stopping.is_set():

			for quality in self.qualities:
				if self.stopping.is_set():
					break

				path = os.path.join(self.base_dir, self.channel, quality)
				hours = [name for name in os.listdir(path) if not name.startswith('.')]
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
					segment_names = [name for name in os.listdir(hour_path) if not name.startswith('.')]


					segment_names.sort()
					parsed = []
					bad_segment_count = 0
					for name in segment_names:
						try:
							parsed.append(common.parse_segment_path(os.path.join(hour_path, name)))
						except ValueError as e:
							self.logger.warn(e)
							bad_segment_count += 1

					#parsed = (common.parse_segment_path(os.path.join(hour_path, name)) for name in segment_names)
					if not parsed:
						self.logger.info('{}/{} is empty'.format(quality, hour))
						continue					

					full_segment_count = 0
					partial_segment_count = 0
					full_segment_duration = datetime.timedelta(0)
					partial_segment_duration = datetime.timedelta(0)
					full_overlaps = 0
					full_overlap_duration = datetime.timedelta(0)
					partial_overlaps = 0
					partial_overlap_duration = datetime.timedelta(0)

					best_segments = []
					holes = []
					editable_holes = []
					previous = None
					previous_editable = None
					coverage = datetime.timedelta(0)
					editable_coverage = datetime.timedelta(0)
					only_partials = []

					for start_time, segments in itertools.groupby(parsed, key=lambda segment: segment.start):
						full_segments = []
						partial_segments = []
						for segment in segments:
							if segment.type == 'full':
								full_segments.append(segment)
								full_segment_count += 1
								full_segment_duration += segment.duration
							elif segment.type == 'partial':
								partial_segments.append(segment)
								partial_segment_count += 1
								partial_segment_duration += segment.duration

						if full_segments:
							if len(full_segments) == 1:
								best_segment = full_segments[0]
							else:
								full_segments.sort(key=lambda segment: (segment.duration))
								best_segment = full_segments[-1]
								for segment in full_segments[:-1]:
									full_overlaps += 1
									full_overlap_duration += segment.duration
							if partial_segments:
								for segment in partial_segments:
									partial_overlaps += 1
									partial_overlap_duration += segment.duration
						else:
							partial_segments.sort(key=lambda segment: (segment.duration))
							best_segment = partial_segments[-1]
							only_partials.append((best_segment.start, best_segment.start + best_segment.duration))
							for segment in partial_segments[:-1]:
								partial_overlaps += 1
								partial_overlap_duration += segment.duration
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

					#handle the case when there is a hole between the last segment and the end of the hour if not the last hour
					if hour != hours[-1] and end < hour_end:
						holes.append((end, hour_end))
						hole_duration += hour_end - end
						editable_holes.append((end, hour_end))
						editable_hole_duration += hour_end - end

					full_segment_count_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(full_segment_count)
					partial_segment_count_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(partial_segment_count)
					bad_segment_count_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(bad_segment_count)
					full_segment_duration_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(full_segment_duration.total_seconds())
					partial_segment_duration_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(partial_segment_duration.total_seconds())
					raw_coverage_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(coverage.total_seconds())
					editable_coverage_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(editable_coverage.total_seconds())
					raw_holes_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(len(holes))
					editable_holes_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(len(editable_holes))
					full_overlap_count_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(full_overlaps)
					partial_overlap_count_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(partial_overlaps)
					full_overlap_duration_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(full_overlap_duration.total_seconds())
					partial_overlap_duration_gauge.labels(channel=self.channel, quality=quality, hour=hour).set(partial_overlap_duration.total_seconds())



					self.logger.info('{}/{}: Start: {} End: {} ({} s)'.format(quality, hour, start, end, (end - start).total_seconds()))
					self.logger.info('{}/{}: {} full segments totalling {} s'.format(quality, hour, full_segment_count, full_segment_duration.total_seconds()))
					self.logger.info('{}/{}: {} bad segments'.format(quality, hour, bad_segment_count))
					self.logger.info('{}/{}: {} overlapping full segments totalling {} s'.format(quality, hour, full_overlaps, full_overlap_duration.total_seconds()))
					self.logger.info('{}/{}: {} partial segments totalling {} s'.format(quality, hour, partial_segment_count, partial_segment_duration.total_seconds()))
					self.logger.info('{}/{}: {} overlapping partial segments totalling {} s'.format(quality, hour, partial_overlaps, partial_overlap_duration.total_seconds()))
					self.logger.info('{}/{}: raw coverage {} s, editable coverage {} s '.format(quality, hour, coverage.total_seconds(), editable_coverage.total_seconds()))
					self.logger.info('{}/{}: {} holes totalling {} s '.format(quality, hour, len(holes), hole_duration.total_seconds()))
					self.logger.info('{}/{}: {} editable holes totalling {} s '.format(quality, hour, len(editable_holes), editable_hole_duration.total_seconds()))
					self.logger.info('Checking {}/{} complete'.format(quality, hour))

					# add holes for the start and end hours for the coverage map
					# do this after updating gauges and logging as these aren't likely real holes, just the start and end of the stream.
					if previous_hour_segments is None:
						holes.append((hour_start, start))
					if hour == hours[-1]:
						holes.append((end, hour_end))


					all_hour_holes[hour] = holes
					all_hour_partials[hour] = only_partials					

					previous_hour_segments = best_segments

				self.create_coverage_map(quality, all_hour_holes, all_hour_partials)

			self.stopping.wait(common.jitter(self.CHECK_INTERVAL))



@argh.arg('channels', nargs='*', help='Channels to check coverage of')
@argh.arg('--base-dir', help='Directory where segments are stored. Default is current working directory.')
@argh.arg('--qualities', help="Qualities of each channel to checked. Comma seperated if multiple. Default is 'source'.")
@argh.arg('--metrics-port', help='Port for Prometheus stats. Default is 8006.')
@argh.arg('--backdoor-port', help='Port for gevent.backdoor access. By default disabled.')
def main(channels, base_dir='.', qualities='source', metrics_port=8006,
		backdoor_port=0):
	"""Segment coverage service"""
	qualities = qualities.split(',') if qualities else []
	qualities = [quality.strip() for quality in qualities]

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)

	managers = []
	workers = []
	for channel in channels:
		logging.info('Starting coverage checks {} with {} as qualities in {}'.format(channel, ', '.join(qualities), base_dir))
		manager = CoverageChecker(channel, qualities, base_dir)
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
