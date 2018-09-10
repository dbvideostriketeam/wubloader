
"""
The central management class which everything else is run from.
Its lifecycle is managed directly by main().
"""


class Wubloader(object):
	def __init__(self, config):
		self.config = config

		self.id = config.get('name', socket.gethostname())
		self.sheets = SheetsManager(config['sheets'], config['creds'])

		self.stopping = False
		self.stopped = gevent.event.Event()

		self.group = gevent.pool.Group()
		self.job = None

		self.group.spawn(self._run)

	def stop(self):
		"""Tell wubloader to gracefully stop by finishing current jobs but starting no new ones."""
		self.stopping = True

	def cancel_all(self):
		"""Tell wubloader to forcefully stop by cancelling current jobs."""
		if self.job:
			self.job.cancel()

	def _run(self):
		# clean up in case of prior unclean shutdown
		self.cleanup_existing()

		with Heartbeat(self.sheets['heartbeat'], self.name, self.group):
			while not self.stopping:
				for job in self.find_jobs():
					# TODO if we're not doing it, handle this and continue
					# TODO if we're doing it, create Job and set self.job
					# TODO wait for it to finish
					# TODO break, to check stopping and restart job list from beginning

		# wait for any remaining tasks to finish
		self.group.join()
		# indicate that we're done
		self.stopped.set()

	def cleanup_existing(self):
		"""Scan for any existing jobs claimed by us, and cancel them."""
		# TODO
