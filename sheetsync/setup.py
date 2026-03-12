from setuptools import setup, find_packages

setup(
	name = "wubloader-cutter",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh==0.29.4",
		"gevent",
		"prometheus-client",
		"psycogreen",
		"psycopg2",
		"python-dateutil",
		"requests",
		"tzdata",
		"urllib3>=2.2.2",
		"wubloader-common",
	],
)
