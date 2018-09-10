
import logging

# Verbose format but includes all extra info
LOG_FORMAT = "[%(asctime)s] %(levelname)s pid:%(process)d tid:%(thread)d %(name)s (%(pathname)s:%(funcName)s:%(lineno)d): %(message)s"


def main(conf_file, log_level='INFO'):
	logging.basicConfig(level=log_level, format=LOG_FORMAT)

	with open(conf_file) as f:
		config = json.load(f)

	
