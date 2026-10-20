from setuptools import setup, find_packages

setup(
	name = "wubloader-common",
	version = "0.0.0",
	packages = find_packages(),
	install_requires = [
		"certifi>=2026.10.19", # eMudhra Intermediate CA Compromise
		"gevent",
		"monotonic",
		"prometheus-client",
		"websockets",
	],
)
