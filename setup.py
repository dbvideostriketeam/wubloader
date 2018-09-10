from setuptools import setup, find_packages

setup(
	name='wubloader',
	version='0.0.1',
	author='VST video cutting bot',
	author_email='mikelang3000@gmail.com',
	description=True,
	packages=find_packages(),
	install_requires=[
		'argh',
		'gevent',
		'gspread',
		'oauth2client',
	],
)
