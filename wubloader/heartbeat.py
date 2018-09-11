
import logging
import time

import gevent


class Heartbeat(object):
	"""Periodically writes current time to the cell associated with this instance,
	indicating it's still alive.
	The given sheet should be rows of the form:
		instance, last update time (in epoch)
	This instance will be added if it doesn't already exist.

	Also keeps track of what other bots are alive in self.alive

	This class is a context manager and will run until exit.
	"""
	# How often to refresh our heartbeat
	HEARTBEAT_INTERVAL = 1
	# How old other bots heartbeat needs to be to consider them dead
	HEARTBEAT_THRESHOLD = 10

	def __init__(self, sheet, name, group):
		self.sheet = sheet
		self.name = name
		self.stopped = gevent.event.Event()

	def __enter__(self):
		self.alive = self._get_alive() # do one now to prevent a race where it's read before it's written
		self.worker = self.group.spawn(self._run)
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
			self.alive = self._get_alive()

		# clear the heartbeat to indicate we're stopping
		row.update(heartbeat="")

	def _get_alive(self):
		alive = set()
		for row in self.sheet:
			if not row.id:
				continue
			try:
				heartbeat = float(row.heartbeat)
			except ValueError:
				logging.warning("Invalid heartbeat value for row {}: {!r}".format(row, row.heartbeat))
				continue
			age = time.time() - heartbeat
			if age > self.HEARTBEAT_THRESHOLD:
				logging.debug("Considering {} dead: heartbeat too old at {} sec".format(row.id, age))
				continue
			alive.add(row.id)
		return alive
