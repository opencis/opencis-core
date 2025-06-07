# setup.py

from setuptools import setup
from Cython.Build import cythonize

setup(
    name="cxl_packets",
    ext_modules=cythonize(["packet_base.pyx", "packet_structs.pyx"]),
    zip_safe=False,
)
