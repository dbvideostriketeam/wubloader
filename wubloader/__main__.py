
import gevent.monkey
gevent.monkey.patch_all()

import logging
logging.basicConfig(level='DEBUG')

import argh

from wubloader.main import main

argh.dispatch_command(main)
