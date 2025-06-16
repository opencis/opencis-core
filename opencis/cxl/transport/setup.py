from setuptools import setup, Extension
from Cython.Build import cythonize
import os

# Simple setup.py that always builds inside this directory
here = os.path.abspath(os.path.dirname(__file__))

setup(
    ext_modules=cythonize(
        [
            Extension("packet_base", [os.path.join(here, "packet_base.pyx")]),
            Extension("packet_structs", [os.path.join(here, "packet_structs.pyx")]),
        ]
    ),
)
