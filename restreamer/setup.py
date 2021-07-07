from setuptools import setup, find_packages

setup(
	name = "wubloader-restreamer",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh",
		"python-dateutil",
		"flask",
		"gevent",
		"monotonic",
		"mysql-connector-python==8.0.5", # old version for py2 compat
		"prometheus-client",
		"wubloader-common",
	],
)
