from setuptools import setup, find_packages

setup(
	name='zulip_bots',
	version='0.0.1',
	author='DB Video Strike Team',
	author_email='dbvideostriketeam@gmail.com',
	description='',
	packages=find_packages(),
	install_requires=[
		'Mastodon.py',
		'PyYAML',
		'argh',
		'beautifulsoup4', # for parsing mastodon posts
		'gevent',
		'requests',
	],
)
