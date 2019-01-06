from setuptools import setup

setup(
	name = "wubloader-common",
	version = "0.0.0",
	py_modules = ["common"],
	install_requires = [
		"monotonic",
		"prometheus-client",
		"python-dateutil",
	],
)
