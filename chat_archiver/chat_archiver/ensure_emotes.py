
import gevent.monkey
gevent.monkey.patch_all()

import argh
import logging
import json

from chat_archiver.main import ensure_emotes, wait_for_ensure_emotes

def main(base_dir, *ids, log='INFO'):
	"""Ensure all listed emote ids are downloaded"""
	logging.basicConfig(level=log)
	ensure_emotes(base_dir, ids)
	wait_for_ensure_emotes()

if __name__ == '__main__':
	argh.dispatch_command(main)
