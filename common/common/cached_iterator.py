
import itertools

import gevent.lock


class CachedIterator():
	"""Wraps an iterator. When you iterate over this, it pulls items from the wrapped iterator
	as needed, but remembers each one. When you iterate over it again, it will re-serve the
	yielded items in the same order, until it runs out, in which case it starts consuming
	from the wrapped iterator again.
	gevent-safe.
	"""
	def __init__(self, iterator):
		self.iterator = iterator # Replaced with None once it's exhausted
		self.error = None # Set if iterator errors, the error is repeated for all future consumption
		self.items = []
		self.lock = gevent.lock.RLock()

	def __iter__(self):
		# We use a loop index here because self.items may lengthen between loops
		for i in itertools.count():
			# are we beyond the end of the array?
			if len(self.items) <= i:
				# If we're more than 1 beyond the end, something has gone horribly wrong.
				# We should've already lengthened it last iteration
				assert len(self.items) == i, "CachedIterator logic error: {} != {}".format(len(self.items), i)
				# Note we don't need the lock up until now because we're only trying to be gevent-safe,
				# not thread-safe. Simple operations like checking lengths can't be interrupted.
				# However calling next on the iterator may cause a switch.
				with self.lock:
					# Taking the lock may have also caused a switch, so we need to re-check
					# our conditions. Someone else may have already added the item we need.
					if len(self.items) <= i:
						# Check if the iterator is still active. If not, we've reached the end or an error.
						if self.iterator is None:
							if self.error is not None:
								raise self.error
							return
						try:
							item = next(self.iterator)
						except StopIteration:
							# We've reached the end. Discard the iterator (in theory an iterator that
							# has raised StopIteration once will keep raising it every time thereafter,
							# but best not to rely on that).
							self.iterator = None
							# And we're done.
							return
						except Exception as ex:
							# Discard the iterator and save the error to be re-served
							self.iterator = None
							self.error = ex
							raise
						self.items.append(item)
			yield self.items[i]
