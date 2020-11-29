from setuptools import setup, find_packages

setup(
	name = 'wubloader-segment_coverage',
	version = '0.0.0',
	packages = find_packages(),
	install_requires = [
		'argh',
		'gevent==1.5a2',
		'matplotlib',
		'numpy',
		'psycogreen',
		'psycopg2',                
		'prometheus-client',
		'python-dateutil',
		'wubloader-common',
	],
)
