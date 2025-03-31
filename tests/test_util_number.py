"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from opencis.util.number import round_up_to_power_of_2


def test_round_up_to_power_of_2():
    assert round_up_to_power_of_2(7) == 8
    assert round_up_to_power_of_2(20) == 32
    assert round_up_to_power_of_2(100) == 128
    assert round_up_to_power_of_2(200) == 256
    assert round_up_to_power_of_2(300) == 512
    assert round_up_to_power_of_2(600) == 1024
    assert round_up_to_power_of_2(2000) == 2048
    assert round_up_to_power_of_2(4000) == 4096
    assert round_up_to_power_of_2(8000) == 8192
    assert round_up_to_power_of_2(12000) == 16384
    assert round_up_to_power_of_2(20000) == 32768
