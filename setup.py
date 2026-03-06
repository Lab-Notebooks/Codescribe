"""Build and installation script for CodeScribe."""

# standard libraries
import re
from setuptools import setup, find_packages

# get long description from README
with open("README.rst", mode="r") as readme:
    long_description = readme.read()

with open("codescribe/__meta__.py", mode="r") as source:
    content = source.read().strip()
    metadata = {
        key: re.search(key + r'\s*=\s*[\'"]([^\'"]*)[\'"]', content).group(1)
        for key in [
            "__pkgname__",
            "__version__",
            "__authors__",
            "__license__",
            "__description__",
        ]
    }

# core dependencies - click, docker, singularity
DEPENDENCIES = []

with open("requirements/core.txt", mode="r", encoding="ascii") as core_reqs:
    DEPENDENCIES = core_reqs.read()


setup(
    name=metadata["__pkgname__"],
    version=metadata["__version__"],
    author=metadata["__authors__"],
    description=metadata["__description__"],
    license=metadata["__license__"],
    packages=find_packages(where="./"),
    package_dir={"": "./"},
    #package_data={
    #    "": [
    #        "resources/Dockerfile.base",
    #        "resources/Dockerfile.root",
    #        "resources/Dockerfile.user",
    #    ]
    #},
    scripts=["codescribe/code-scribe"],
    include_package_data=True,
    long_description=long_description,
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "License :: OSI Approved :: Apache Software License",
    ],
    install_requires=DEPENDENCIES,
)
