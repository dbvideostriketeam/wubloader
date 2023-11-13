from setuptools import setup, find_packages

setup(
    name = 'graphs',
    version = '0.0.0',
    packages = find_packages(),
    install_requires = [
            'argh',
            'bokeh',
            'gevent',
            'requests'
    ],
)
