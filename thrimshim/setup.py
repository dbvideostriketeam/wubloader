from setuptools import setup, find_packages

setup(
	name = "wubloader-thrimshim",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh",
		"flask",
		"gevent",
		"google-auth",
		"psycogreen",
		"psycopg2",
		"requests",
		"wubloader-common",
	],
)
