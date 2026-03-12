from setuptools import setup, find_packages

setup(
	name = "wubloader-playlist-manager",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh==0.29.4",
		"gevent",
		"prometheus-client",
		"psycogreen",
		"psycopg2",
		"requests",
		"wubloader-common",
	],
)
