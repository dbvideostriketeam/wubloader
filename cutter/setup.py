from setuptools import setup, find_packages

setup(
	name = "wubloader-cutter",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh",
		"gevent",
		"prometheus-client",
		"psycogreen",
		"psycopg2-binary",
		"requests",
		"wubloader-common",
	],
)
