from setuptools import setup, find_packages

setup(
	name = "wubloader-downloader",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh",
		"python-dateutil",
		"gevent",
		"monotonic",
		"requests",
		"wubloader-common",
	],
)
