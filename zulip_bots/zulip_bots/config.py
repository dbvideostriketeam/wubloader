import json
import logging
import os

import yaml

import prometheus_client as prom

import common

def get_config(conf_file):
	if conf_file.startswith("{"):
		return json.loads(conf_file)
	else:
		with open(conf_file) as f:
			return yaml.safe_load(f)

def common_setup(metrics_port):
	logging.basicConfig(level=os.environ.get('WUBLOADER_LOG_LEVEL', 'INFO').upper())

	common.PromLogCountsHandler.install()
	common.install_stacksampler()
	prom.start_http_server(metrics_port)
