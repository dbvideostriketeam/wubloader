from setuptools import setup, find_packages

setup(
    name = "wubloader-buscribe-api",
    version = "0.0.0",
    packages = find_packages(),
    install_requires = [
        "argh",
        "psycopg2",
        "gevent==1.5a2",
        "greenlet==0.4.16",
        "psycogreen",
        "wubloader-common",
        "python-dateutil",
        "flask"
    ],
)
