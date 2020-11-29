from setuptools import setup, find_packages

setup(
	name = "wubloader-downloader",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh",
		"python-dateutil",
		"gevent==1.5a2",
		"monotonic",
		"prometheus-client==0.7.1", # locked version as we rely on internals
		"requests",
		"wubloader-common",
	],
)
