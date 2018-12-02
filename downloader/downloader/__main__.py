import logging

import argh

from downloader.main import main

logging.basicConfig(level=logging.INFO)
argh.dispatch_command(main)
