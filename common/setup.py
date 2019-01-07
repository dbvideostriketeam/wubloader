from setuptools import setup, find_packages

setup(
	name = "wubloader-common",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"monotonic",
		"prometheus-client",
		"python-dateutil",
	],
)
