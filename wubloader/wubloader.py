
"""
The central management class which everything else is run from.
Its lifecycle is managed directly by main().
"""

from calendar import timegm
import logging
import time
import socket

import gevent.event
import gevent.pool

from .heartbeat import Heartbeat
from .job import Job
from .sheets import SheetsManager
from . import states


class Wubloader(object):
	JOBS_POLL_INTERVAL = 0.5

	def __init__(self, config):
		self.config = config

		self.bustime_base = timegm(time.strptime(config['bustime_start'], '%Y-%m-%dT%H:%M:%SZ'))

		self.name = config.get('name', socket.gethostname())
		self.sheets = SheetsManager(config['sheets'], config['creds'])

		self.stopping = False
		self.stopped = gevent.event.Event()

		# self.group contains all sub-greenlets and is used to ensure they're all shut down before exiting
		self.group = gevent.pool.Group()
		# self.job is kept as a seperate reference here so it's cancellable
		self.job = None
		# self.uploads is a group tracking all currently ongoing uploads.
		# note it's a subset of self.group
		self.uploads = gevent.pool.Group()

		self.heartbeat = Heartbeat(self.sheets['heartbeat'], self.name, self.group)

		gevent.spawn(self._run)

	def stop(self):
		"""Tell wubloader to gracefully stop by finishing current jobs but starting no new ones."""
		self.stopping = True

	def cancel_all(self):
		"""Tell wubloader to forcefully stop by cancelling current jobs."""
		if self.job:
			self.job.cancel()
		self.uploads.kill(block=False)

	def _run(self):
		# clean up in case of prior unclean shutdown
		self.cleanup_existing()

		# heartbeat will periodically update a sheet to indicate we're alive,
		# and tell us who else is alive.
		with self.heartbeat:
			while not self.stopping:
				for job in self.find_jobs():

					# If it's already claimed (except by us), ignore it.
					# Note this check considers a claim by a dead bot to be invalid (except for publishes).
					if job.uploader and job.uploader != self.name:
						continue

					# If we're not allowed to claim it, ignore it.
					if self.name.lower() in job.excluded:
						continue

					# Acceptance checks
					try:
						# Checking duration exercises start time and end time parsing,
						# which raise ValueError if they're bad.
						if job.duration <= 0:
							raise ValueError("Duration is {} sec, which is <= 0".format(job.duration))
					except ValueError as e:
						# Note that as acceptance checks are fixable, we do not put job into an error state.
						# Job will proceed as soon as it's fixed.
						# We only inform user of errors if notes field is blank to avoid overwriting more important info.
						if not job.row.notes:
							job.row.update(notes="Acceptance check failed: {}".format(e))
						continue
					# Acceptance tests passed, remove existing note on failed checks if present
					if job.row.notes.startswith("Acceptance check failed: "):
						job.row.update(notes="")

					# Do we have all the data?
					# TODO if we don't, check if end time is recent. if so, skip for now.
					#      if not, initiate claim-with-holes process

					# We've claimed the job, process it.
					self.job = job
					self.job.process()

					# Exit the loop to check stopping and restart our scan for eligible jobs.
					break

				else:
					# We reached the end of the jobs list and didn't find any jobs to do
					gevent.sleep(self.JOBS_POLL_INTERVAL)

		# wait for any remaining tasks to finish
		self.group.join()
		# indicate that we're done
		self.stopped.set()

	def cleanup_existing(self):
		"""Scan for any existing non-publish rows claimed by us, and cancel them."""
		for job in self.find_jobs():
			if job.row.uploader == self.name and job.row.state != states.rollback(job.row.state):
				logging.warning("Found existing in progress job for us, clearing")
				job.row.update(state=states.rollback(job.row.state))
				if job.job_type != 'publish':
					job.row.update(uploader="")

	def find_jobs(self):
		"""Return potential jobs (based only on state), in priority order."""
		jobs = []
		for sheet_type in ('main', 'chunks'):
			for sheet in self.sheets[sheet_type]:
				for row in sheet:
					if row.state in states.IS_ACTIONABLE:
						jobs.append(Job(self, sheet_type == 'chunks', sheet, row))
		return sorted(jobs, key=lambda job: job.priority)
