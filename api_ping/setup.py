from setuptools import setup, find_packages

setup(
	name = "wubloader-api-ping",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"argh==0.29.4",
		"requests",
		"wubloader-common",
	],
)
