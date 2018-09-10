


class Heartbeat(object):
	"""Periodically writes current time to the cell associated with this instance,
	indicating it's still alive.
	The given sheet should be rows of the form:
		instance, last update time (in epoch)
	This instance will be added if it doesn't already exist.

	This class is a context manager and will run until exit.
	"""
	HEARTBEAT_INTERVAL = 1

	def __init__(self, sheet, name, group):
		self.sheet = sheet
		self.name = name
		self.stopped = gevent.event.Event()

	def __enter__(self):
		self.worker = group.spawn(self._run)
		return self

	def __exit__(self, *exc_info):
		self.stopped.set()

	def _run(self):
		row = self.sheet[self.name]
		if not row:
			# it doesn't already exist, create it
			row = self.sheet.append(id=self.name, heartbeat=time.time())
		while not self.stopped.wait(self.HEARTBEAT_INTERVAL):
			row.update(heartbeat=time.time())
		# clear the heartbeat to indicate we're stopping
		row.update(heartbeat="")
