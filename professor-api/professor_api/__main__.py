import logging
import os

import argh

from professor_api.main import main

LOG_FORMAT = "[%(asctime)s] %(levelname)8s %(name)s(%(module)s:%(lineno)d): %(message)s"

level = os.environ.get('WUBLOADER_LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=level, format=LOG_FORMAT)
argh.dispatch_command(main)
