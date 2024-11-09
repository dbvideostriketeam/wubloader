from setuptools import setup, find_packages

setup(
	name = "wubloader-cutter",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh==0.28.1",
		"gevent",
		"exceptiongroup", # backport from python 3.11
		"prometheus-client==0.7.1", # locked version as we rely on internals
		"psycogreen",
		"psycopg2",
		"python-dateutil",
		"requests",
		"tzdata",
		"urllib3",
		"wubloader-common",
	],
)
