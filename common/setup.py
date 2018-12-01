from setuptools import setup

setup(
	name = "wubloader-common",
	version = "0.0.0",
	py_modules = ["common.py"],
	install_requires = [
		"dateutil",
		"PyYAML<4.0.0",
	],
)
