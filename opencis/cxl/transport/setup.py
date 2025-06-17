"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import os
from setuptools import setup, Extension
from Cython.Build import cythonize

here = os.path.abspath(os.path.dirname(__file__))

setup(
    ext_modules=cythonize(
        [
            Extension("packet_base", [os.path.join(here, "packet_base.pyx")]),
            Extension("packet_structs", [os.path.join(here, "packet_structs.pyx")]),
        ]
    ),
)
