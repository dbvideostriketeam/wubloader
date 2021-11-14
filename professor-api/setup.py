from setuptools import setup, find_packages

setup(
    name = "wubloader-professor-api",
    version = "0.0.0",
    packages = find_packages(),
    install_requires = [
        "argh",
        "psycopg2",
        "gevent",
        "psycogreen",
        "wubloader-common",
        "python-dateutil",
        "flask",
        "google-auth"
    ],
)
