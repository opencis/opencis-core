"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from enum import IntEnum, auto
import pytest


@pytest.fixture
def get_gold_std_reg_vals():
    def _get_gold_std_reg_vals(device_type: str):
        with open("tests/regvals.txt") as f:
            for line in f:
                (k, v) = line.strip().split(":")
                if k == device_type:
                    return v
        return None

    return _get_gold_std_reg_vals


class TEST_PORT(IntEnum):
    TEST_1 = auto()
    TEST_2 = auto()
    TEST_3 = auto()
    TEST_4 = auto()
    TEST_5 = auto()
    TEST_6 = auto()
    TEST_7 = auto()
    TEST_8 = auto()
    TEST_9 = auto()
    TEST_10 = auto()
    TEST_11 = auto()
    TEST_12 = auto()
    TEST_13 = auto()
    TEST_14 = auto()


def pytest_configure():
    pytest.PORT = TEST_PORT
