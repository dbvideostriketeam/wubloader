from setuptools import setup, find_packages

setup(
	name = "wubloader-thrimshim",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh==0.29.4",
		"flask",
		"gevent",
		"google-auth",
		"PyJWT[crypto]>=2.10.1,<3",
		"psycogreen",
		"psycopg2",
		"python-dateutil",
		"requests",
		"wubloader-common",
	],
)
