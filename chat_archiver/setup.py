from setuptools import setup, find_packages

setup(
	name='chat_archiver',
	version='0.0.1',
	author='Mike Lang',
	author_email='mikelang3000@gmail.com',
	description='',
	packages=find_packages(),
	install_requires=[
		'argh==0.28.1',
		'gevent',
		'monotonic',
		'requests', # for emote fetching
	],
)
