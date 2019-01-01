from setuptools import setup, find_packages

setup(
	name = "wubloader-backfiller",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"requests",
		"wubloader-common",
	],
)
