
import argh
import logging

from .main import merge_all

def main(path, log='INFO'):
	"""Merge all batch files with the same timestamp within given directory"""
	logging.basicConfig(level=log)
	merge_all(path)

if __name__ == '__main__':
	argh.dispatch_command(main)
