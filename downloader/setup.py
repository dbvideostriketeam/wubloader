from setuptools import setup, find_packages

setup(
	name = "wubloader-downloader",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh==0.29.4",
		"python-dateutil",
		"gevent",
		"monotonic",
		"prometheus-client",
		"requests",
		"wubloader-common",
	],
)
