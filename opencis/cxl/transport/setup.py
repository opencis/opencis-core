"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import os
from setuptools import setup, Extension
from Cython.Build import cythonize

here = os.path.abspath(os.path.dirname(__file__))


common_cflags = [
    "-O3",
    "-g",
    "-fno-omit-frame-pointer",
    "-march=native",
]

ext_modules = cythonize(
    [
        Extension(
            "packet_base",
            [os.path.join(here, "packet_base.pyx")],
            extra_compile_args=common_cflags,
            extra_link_args=["-g"],
        ),
        Extension(
            "packet_structs",
            [os.path.join(here, "packet_structs.pyx")],
            extra_compile_args=common_cflags,
            extra_link_args=["-g"],
        ),
    ],
    compiler_directives={
        "boundscheck": False,
        "wraparound": False,
        "initializedcheck": False,
        "cdivision": True,
    },
)

setup(
    name="my-packet-lib",
    ext_modules=ext_modules,
)
