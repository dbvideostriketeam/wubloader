from setuptools import setup, find_packages

setup(
	name = "wubloader-cutter",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh==0.29.4",
		"gevent",
		"Pillow", # for thumbnail templating
		"prometheus-client",
		"psycogreen",
		"psycopg2",
		"requests",
		"wubloader-common",
	],
)
