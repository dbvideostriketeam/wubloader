from setuptools import setup, find_packages

setup(
	name = "wubloader-backfiller",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh==0.28.1",
		"gevent",
		"psycogreen",
		"psycopg2",
		"python-dateutil",
		"requests",
		"wubloader-common",
	],
)
