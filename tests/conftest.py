"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

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
