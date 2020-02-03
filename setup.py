import io
import os
import re
import setuptools


def read(*names, **kwargs):
    with io.open(os.path.join(os.path.dirname(__file__), *names), encoding=kwargs.get("encoding", "utf8")) as fp:
        return fp.read()


def find_version(*file_paths):
    version_file = read(*file_paths)
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")


setuptools.setup(
    name="zabbix-docker",
    version=find_version("zabbixdocker", "version.py"),
    description="Docker monitoring agent for Zabbix",
    author="Boris HUISGEN",
    author_email="bhuisgen@hbis.fr",
    url="https://github.com/bhuisgen/zabbix-docker",
    download_url="https://github.com/bhuisgen/zabbix-docker",
    packages=setuptools.find_packages(exclude=["*.tests", "*.tests.*", "tests.*", "tests"]),
    install_requires=["docker", "xdg"]
)
