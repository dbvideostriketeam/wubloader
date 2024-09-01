
"""A group of greenlets running tasks.
Each task has a key. If a task with that key is already running,
it is not re-run."""

import gevent


class KeyedGroup:
	def __init__(self):
		self.greenlets = {}

	def spawn(self, key, func, *args, **kwargs):
		if key not in self.greenlets:
			self.greenlets[key] = gevent.spawn(self._wrapper, key, func, *args, **kwargs)
		return self.greenlets[key]

	def wait(self):
		"""Blocks until all tasks started before wait() was called are finished."""
		gevent.wait(self.greenlets.values())

	def _wrapper(self, key, func, *args, **kwargs):
		try:
			return func(*args, **kwargs)
		finally:
			assert self.greenlets[key] is gevent.getcurrent()
			del self.greenlets[key]
