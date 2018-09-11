
import json
import logging
import signal

import gevent

from .wubloader import Wubloader


# Verbose format but includes all extra info
LOG_FORMAT = "[%(asctime)s] %(levelname)s pid:%(process)d tid:%(thread)d %(name)s (%(pathname)s:%(funcName)s:%(lineno)d): %(message)s"


def main(conf_file, log_level='INFO', backdoor=None):
	logging.basicConfig(level=log_level, format=LOG_FORMAT)

	with open(conf_file) as f:
		config = json.load(f)

	wubloader = Wubloader(config)

	# debugging backdoor listening on given localhost port
	if backdoor:
		gevent.backdoor.BackdoorServer(('localhost', int(backdoor)), locals=locals()).start()

	# Set up a queue to receive and handle incoming graceful shutdown signals
	signal_queue = gevent.queue.Queue()
	def on_signal():
		signal_queue.put(None)
	# Gracefully shut down on INT or TERM
	for sig in (signal.SIGINT, signal.SIGTERM):
		gevent.signal(sig, on_signal)
	# Since forcefully raising a KeyboardInterrupt to see where you're stuck is useful for debugging,
	# remap that to SIGQUIT.
	# Note that signal.signal() will run _immediately_ whereas gevent.signal() waits until current
	# greenlet is blocking.
	def raise_interrupt(frame, signum):
		raise KeyboardInterrupt
	signal.signal(signal.SIGQUIT, raise_interrupt)

	signal_queue.get() # block until shutdown
	logging.info("Interrupt received. Finishing existing jobs and exiting. Interrupt again to exit immediately.")
	wubloader.stop()

	# block until shutdown complete OR second shutdown signal
	waiter = gevent.spawn(signal_queue.get)
	gevent.wait([wubloader.stopped, waiter], count=1)
	if not wubloader.stopped.ready():
		logging.warning("Second interrupt recieved. Doing basic cleanup and exiting immediately.")
		wubloader.cancel_all()
