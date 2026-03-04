from setuptools import setup, find_packages

setup(
    name = "wubloader-buscribe",
    version = "0.0.0",
    packages = find_packages(),
    install_requires = [
        "argh==0.29.4",
        "psycopg2",
	    "gevent",
        "psycogreen",
        "wubloader-common",
        "python-dateutil",
        "vosk"
    ],
)
