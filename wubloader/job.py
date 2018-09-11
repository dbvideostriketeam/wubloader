
import logging

from . import states


class Job(object):
	"""A job wraps a row and represents a video cutting job to do."""

	# How often to check if someone else has claimed a row out from underneath us.
	OWNERSHIP_CHECK_INTERVAL = 1

	def __init__(self, wubloader, is_chunk, sheet, row):
		self.wubloader = wubloader
		if is_chunk:
			self.job_type = 'chunk'
		elif row.state in states.FLOWS['draft']:
			self.job_type = 'draft'
		else:
			assert row.state in states.FLOWS['publish']
			self.job_type = 'publish'
		self.sheet = sheet
		self.row = row

	@property
	def priority(self):
		"""User-set priority is most important, followed by type, then earliest first."""
		type_priority = ['chunk', 'draft', 'publish'] # low to high priority
		return (
			getattr(self.row, 'priority', 0), # chunks don't have priority, default to 0
			type_priority.index(self.job_type),
			-self.sheet.id, # sheet index, low number is high priority
			-self.row.index, # row index, low number is high priority
		)

	@property
	def uploader(self):
		"""A processed uploader check that ignores dead bots"""
		return self.row.uploader if self.row.uploader in self.wubloader.heartbeat.alive else ""

	@property
	def excluded(self):
		"""Bots that may not claim this row. NOTE: All lowercase."""
		if not self.row.excluded.strip():
			return []
		return [name.strip().lower() for name in self.row.excluded.split(',')]

	@property
	def start_time(self):
		try:
			return parse_bustime(self.wubloader.bustime_base, self.row.start_time)
		except ValueError as e:
			raise ValueError("Start time: {}".format(e))

	@property
	def end_time(self):
		try:
			return parse_bustime(self.wubloader.bustime_base, self.row.end_time)
		except ValueError as e:
			raise ValueError("End time: {}".format(e))

	@property
	def duration(self):
		return self.end_time - self.start_time

	def cancel(self):
		"""Cancel job that is currently being processed, setting it back to its starting state."""
		if not self.worker.ready():
			# By setting uploader to blank, the watchdog will stop the in-progress job.
			self.row.update(state=states.FLOWS[self.job_type][0], uploader="")

	def process(self):
		"""Call this to perform the job."""
		# We do the actual work in a seperate greenlet so we can easily cancel it.
		self.worker = self.wubloader.group.spawn(self._process)
		# While that does the real work, we poll the uploader field to check no-one else has stolen it.
		while not self.worker.ready():
			# Sleep until either worker is done or interval has passed
			self.worker.join(self.OWNERSHIP_CHECK_INTERVAL)
			# Check if we're still valid
			row = self.row.refresh()
			if row is None or row.uploader != self.row.uploader:
				# Our row's been stolen, cancelled, or just plain lost.
				# Abort with no rollback - let them have it.
				logging.warning("Job {} aborted: Row {} is {}".format(self, self.row,
					"gone" if row is None
					else "cancelled" if row.uploader == ""
					else "claimed by {}".format(row.uploader)
				))
				self.worker.kill(block=True)
				break
		# This will re-raise exception if _process() failed
		self.worker.get()

	def _process(self):
		"""Does the actual cut and upload. You should call process() instead."""
		in_progress = states.FLOWS[self.job_type][1]
		self.row.update(state=in_progress)
		self._cut_video()
		if self.job_type == "draft":
			done = states.FLOWS[self.job_type][-1]
			self.row.update(state=done)
			return
		# Set the upload going before returning
		self.wubloader.group.spawn(self._upload)

	def _cut_video(self):
		# TODO

	def _upload(self):
		# TODO
		# NOTE that if upload fails it should flag for humans


def parse_bustime(base, value):
	parts = value.strip().split(':')
	if len(parts) == 2:
		hours = int(parts[0])
		mins = float(parts[1])
		secs = 0
	elif len(parts) == 3:
		hours = int(parts[0])
		mins = int(parts[1])
		secs = float(parts[2])
	else:
		raise ValueError("Bad format: Must be HH:MM or HH:MM:SS")
	return base + hours * 3600 + mins * 60 + secs
