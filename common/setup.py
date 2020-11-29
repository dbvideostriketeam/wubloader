from setuptools import setup, find_packages

setup(
	name = "wubloader-common",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"gevent==1.5a2",
		"monotonic",
		"prometheus-client",
	],
)
