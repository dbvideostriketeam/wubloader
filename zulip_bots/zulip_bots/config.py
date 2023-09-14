import json

import yaml

def get_config(conf_file):
	if conf_file.startswith("{"):
		return json.loads(conf_file)
	else:
		with open(conf_file) as f:
			return yaml.safe_load(f)


