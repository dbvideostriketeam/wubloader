from setuptools import setup, find_packages

setup(
	name = "wubloader-thrimshim",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh",
		"flask",
		"gevent",
		"psycogreen",
		"psycopg2",
		"python-dateutil",
		"wubloader-common",
	],
)
