"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import Enum, auto


class CXL_COMPONENT_TYPE(Enum):
    P = auto()
    D1 = auto()
    D2 = auto()  # SLD
    LD = auto()  # LDs within MLD
    FMLD = auto()
    UP1 = auto()
    DP1 = auto()
    R = auto()
    RC = auto()
    USP = auto()
    DSP = auto()
    T1 = auto()  # reserved for type 1
    T2 = auto()  # reserved for type 2
