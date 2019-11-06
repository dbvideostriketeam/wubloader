
import atexit
import functools
import logging
import os
import signal
import sys

import gevent.lock
from monotonic import monotonic
import prometheus_client as prom


# need to keep global track of what metrics we've registered
# because we're not allowed to re-register
metrics = {}


def timed(name=None,
	buckets=[10.**x for x in range(-9, 5)], normalized_buckets=None,
	normalize=None,
	**labels
):
	"""Decorator that instruments wrapped function to record real, user and system time
	as a prometheus histogram.

	Metrics are recorded as NAME_latency, NAME_cputime{type=user} and NAME_cputime{type=system}
	respectively. User and system time are process-wide (which means they'll be largely meaningless
	if you're using gevent and the wrapped function blocks) and do not include subprocesses.

	NAME defaults to the wrapped function's name.
	NAME must be unique OR have the exact same labels as other timed() calls with that name.

	Any labels passed in are included. Given label values may be callable, in which case
	they are passed the input and result from the wrapped function and should return a label value.
	Otherwise the given label value is used directly. All label values are automatically str()'d.

	In addition, the "error" label is automatically included, and set to "" if no exception
	occurs, or the name of the exception type if one does.

	The normalize argument, if given, causes the creation of a second set of metrics
	NAME_normalized_latency, etc. The normalize argument should be a callable which
	takes the input and result of the wrapped function and returns a normalization factor.
	All normalized metrics divide the observed times by this factor.
	The intent is to allow a function which is expected to take longer given a larger input
	to be timed on a per-input basis.
	As a special case, when normalize returns 0 or None, normalized metrics are not updated.

	The buckets kwarg is as per prometheus_client.Histogram. The default is a conservative
	but sparse range covering nanoseconds to hours.
	The normalized_buckets kwarg applies to the normalized metrics, and defaults to the same
	as buckets.

	All callables that take inputs and result take them as follows: The first arg is the result,
	followed by *args and **kwargs as per the function's inputs.
	If the wrapped function errored, result is None.
	To simplify error handling in these functions, any errors are taken to mean None,
	and None is interpreted as '' for label values.

	Contrived Example:
		@timed("scanner",
			# constant label
			foo="my example label",
			# label dependent on input
			all=lambda results, predicate, list, find_all=False: find_all,
			# label dependent on output
			found=lambda results, *a, **k: len(found) > 0,
			# normalized on input
			normalize=lambda results, predicate, list, **k: len(list),
		)
		def scanner(predicate, list, find_all=False):
			results = []
			for item in list:
				if predicate(item):
					results.append(item)
					if not find_all:
						break
			return results
	"""

	if normalized_buckets is None:
		normalized_buckets = buckets
	# convert constant (non-callable) values into callables for consistency
	labels = {
		# there's a pyflakes bug here suggesting that v is undefined, but it isn't
		k: v if callable(v) else (lambda *a, **k: v)
		for k, v in labels.items()
	}

	def _timed(fn):
		# can't safely assign to name inside closure, we use a new _name variable instead
		_name = fn.__name__ if name is None else name

		if _name in metrics:
			latency, cputime = metrics[_name]
		else:
			latency = prom.Histogram(
				"{}_latency".format(_name),
				"Wall clock time taken to execute {}".format(_name),
				labels.keys() + ['error'],
				buckets=buckets,
			)
			cputime = prom.Histogram(
				"{}_cputime".format(_name),
				"Process-wide consumed CPU time during execution of {}".format(_name),
				labels.keys() + ['error', 'type'],
				buckets=buckets,
			)
			metrics[_name] = latency, cputime
		if normalize:
			normname = '{} normalized'.format(_name)
			if normname in metrics:
				normal_latency, normal_cputime = metrics[normname]
			else:
				normal_latency = prom.Histogram(
					"{}_latency_normalized".format(_name),
					"Wall clock time taken to execute {} per unit of work".format(_name),
					labels.keys() + ['error'],
					buckets=normalized_buckets,
				)
				normal_cputime = prom.Histogram(
					"{}_cputime_normalized".format(_name),
					"Process-wide consumed CPU time during execution of {} per unit of work".format(_name),
					labels.keys() + ['error', 'type'],
					buckets=normalized_buckets,
				)
				metrics[normname] = normal_latency, normal_cputime

		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			start_monotonic = monotonic()
			start_user, start_sys, _, _, _ = os.times()

			try:
				ret = fn(*args, **kwargs)
			except Exception:
				ret = None
				error_type, error, tb = sys.exc_info()
			else:
				error = None

			end_monotonic = monotonic()
			end_user, end_sys, _, _, _ = os.times()
			wall_time = end_monotonic - start_monotonic
			user_time = end_user - start_user
			sys_time = end_sys - start_sys

			label_values = {}
			for k, v in labels.items():
				try:
					value = v(ret, *args, **kwargs)
				except Exception:
					value = None
				label_values[k] = '' if value is None else str(value)
			label_values.update(error='' if error is None else type(error).__name__)

			latency.labels(**label_values).observe(wall_time)
			cputime.labels(type='user', **label_values).observe(user_time)
			cputime.labels(type='system', **label_values).observe(sys_time)
			if normalize:
				try:
					factor = normalize(ret, *args, **kwargs)
				except Exception:
					factor = None
				if factor is not None and factor > 0:
					normal_latency.labels(**label_values).observe(wall_time / factor)
					normal_cputime.labels(type='user', **label_values).observe(user_time / factor)
					normal_cputime.labels(type='system', **label_values).observe(sys_time / factor)

			if error is None:
				return ret
			raise error_type, error, tb # re-raise error with original traceback

		return wrapper

	return _timed


log_count = prom.Counter("log_count", "Count of messages logged", ["level", "module", "function"])

class PromLogCountsHandler(logging.Handler):
	"""A logging handler that records a count of logs by level, module and function."""
	def emit(self, record):
		log_count.labels(record.levelname, record.module, record.funcName).inc()

	@classmethod
	def install(cls):
		root_logger = logging.getLogger()
		root_logger.addHandler(cls())


def install_stacksampler(interval=0.005):
	"""Samples the stack every INTERVAL seconds of user time.
	We could use user+sys time but that leads to interrupting syscalls,
	which may affect performance, and we care mostly about user time anyway.
	"""
	if os.environ.get('WUBLOADER_DISABLE_STACKSAMPLER', '').lower() == 'true':
		logging.info("Not installing stacksampler - disabled by WUBLOADER_DISABLE_STACKSAMPLER env var")
		return

	# Note we only start each next timer once the previous timer signal has been processed.
	# There are two reasons for this:
	# 1. Avoid handling a signal while already handling a signal, however unlikely,
	#    as this could lead to a deadlock due to locking inside prometheus_client.
	# 2. Avoid biasing the results by effectively not including the time taken to do the actual
	#    stack sampling.

	flamegraph = prom.Counter(
		"flamegraph",
		"Approx time consumed by each unique stack trace seen by sampling the stack",
		["stack"]
	)
	# HACK: It's possible to deadlock if we handle a signal during a prometheus collect
	# operation that locks our flamegraph metric. We then try to take the lock when recording the
	# metric, but can't.
	# As a hacky work around, we replace the lock with a dummy lock that doesn't actually lock anything.
	# This is reasonably safe. We know that only one copy of sample() will ever run at once,
	# and nothing else but sample() and collect() will touch the metric, leaving two possibilities:
	# 1. Multiple collects happen at once: Safe. They only do read operations.
	# 2. A sample during a collect: Safe. The collect only does a copy inside the locked part,
	#    so it just means it'll either get a copy with the new label set, or without it.
	# This presumes the implementation doesn't change to make that different, however.
	flamegraph._lock = gevent.lock.DummySemaphore()
	# There is also a lock we need to bypass on the actual counter values themselves.
	# Since they get created dynamically, this means we need to replace the lock function
	# that is used to create them.
	# This unfortunately means we go without locking for all metrics, not just this one,
	# however this is safe because we are using gevent, not threading. The lock is only
	# used to make incrementing/decrementing the counter thread-safe, which is not a concern
	# under gevent since there are no switch points under the lock.
	import prometheus_client.values
	prometheus_client.values.Lock = gevent.lock.DummySemaphore


	def sample(signum, frame):
		stack = []
		while frame is not None:
			stack.append(frame)
			frame = frame.f_back
		# format each frame as FUNCTION(MODULE)
		stack = ";".join(
			"{}({})".format(frame.f_code.co_name, frame.f_globals.get('__name__'))
			for frame in stack[::-1]
		)
		# increase counter by interval, so final units are in seconds
		flamegraph.labels(stack).inc(interval)
		# schedule the next signal
		signal.setitimer(signal.ITIMER_VIRTUAL, interval)

	def cancel():
		signal.setitimer(signal.ITIMER_VIRTUAL, 0)
	atexit.register(cancel)

	signal.signal(signal.SIGVTALRM, sample)
	# deliver the first signal in INTERVAL seconds
	signal.setitimer(signal.ITIMER_VIRTUAL, interval)



