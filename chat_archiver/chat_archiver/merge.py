
import argh
import logging
import json

from common.chat import merge_messages, format_batch

def main(*paths, log='INFO'):
	"""Merge all listed batch files and output result to stdout"""
	logging.basicConfig(level=log)
	messages = []
	for path in paths:
		with open(path) as f:
			batch = f.read()
		batch = [json.loads(line) for line in batch.strip().split("\n")]
		messages = merge_messages(messages, batch)
	print(format_batch(messages))

if __name__ == '__main__':
	argh.dispatch_command(main)
