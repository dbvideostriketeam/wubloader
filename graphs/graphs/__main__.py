import gevent.monkey
gevent.monkey.patch_all()

import logging

import argh

from graphs.main import main
# from main import main

LOG_FORMAT = "[%(asctime)s] %(levelname)8s %(name)s(%(module)s:%(lineno)d): %(message)s"

logging.basicConfig(level='INFO', format=LOG_FORMAT)
argh.dispatch_command(main)
