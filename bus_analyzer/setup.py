from setuptools import setup, find_packages

setup(
	name='bus_analyzer',
	version='0.0.1',
	author='DB Video Strike Team',
	author_email='dbvideostriketeam@gmail.com',
	description='',
	packages=find_packages(),
	install_requires=[
		"argh==0.28.1",
		"gevent",
        "psycogreen",
        "psycopg2",
		"python-dateutil",
		"wubloader-common",
	],
)
