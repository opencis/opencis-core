"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import sys
import os
import random
from typing import Generator


def round_up_to_power_of_2(number: int) -> int:
    # Subtract 1 from the number
    number -= 1

    # Perform bitwise OR with the number and its right-shifted value
    number |= number >> 1
    number |= number >> 2
    number |= number >> 4
    number |= number >> 8
    number |= number >> 16

    # Add 1 to the result to get the next power of 2
    number += 1

    return number


def get_rand_range_generator(base, length):
    nums = random.sample(range(base, base + length), length)
    for num in nums:
        print(f"port:{num}")
        yield num


def get_randbits(n_bits: int):
    # truly random via /dev/random
    s = os.urandom(100)
    random.seed(s)
    return random.getrandbits(n_bits)


def bswap16(n):
    return ((n & 0xFF00) >> 8) | ((n & 0x00FF) << 8)


def bswap32(n):
    return (
        ((n & 0xFF000000) >> 24)
        | ((n & 0x00FF0000) >> 8)
        | ((n & 0x0000FF00) << 8)
        | ((n & 0x000000FF) << 24)
    )


def bswap64(n):
    return (
        ((n & 0xFF00000000000000) >> 56)
        | ((n & 0x00FF000000000000) >> 40)
        | ((n & 0x0000FF0000000000) >> 24)
        | ((n & 0x000000FF00000000) >> 8)
        | ((n & 0x00000000FF000000) << 8)
        | ((n & 0x0000000000FF0000) << 24)
        | ((n & 0x000000000000FF00) << 40)
        | ((n & 0x00000000000000FF) << 56)
    )


def to_be16(n):
    if sys.byteorder == "big":
        return n
    return bswap16(n)


def to_be32(n):
    if sys.byteorder == "big":
        return n
    return bswap32(n)


def to_be64(n):
    if sys.byteorder == "big":
        return n
    return bswap64(n)


def htotlp16(n):
    return to_be16(n)


def htotlp32(n):
    return to_be32(n)


def htotlp64(n):
    return to_be64(n)


def tlptoh16(n):
    if sys.byteorder == "big":
        return n
    return bswap16(n)


def tlptoh32(n):
    if sys.byteorder == "big":
        return n
    return bswap32(n)


def tlptoh64(n):
    if sys.byteorder == "big":
        return n
    return bswap64(n)


def split_int(cacheline: int, line_length: int = 64, stride: int = 8) -> Generator[int, int, None]:
    for unit in range(line_length - stride, -1, -stride):
        bmask = ~((1 << unit) - 1)
        masked = cacheline & bmask
        yield masked >> unit
        cacheline -= masked


def extract_upper(from_what: int, how_much: int, how_long: int):
    """
    Extracts and returns the upper `how_much` bits from `from_what`.
    `from_what` is assumed to be `how_long` bits long.
    If `from_what` could not possibly be `how_long` bits long,
    ValueError is raised.
    If `how_much > how_long`, then for obvious reasons ValueError
    is raised again.
    Ex. `extract_upper(0b1101010010, 5, 12) == 0b00110`.
    `extract_upper(0b10000010, 1, 2) -> ValueError`
    """
    if from_what >= (1 << how_long):
        raise ValueError(f"{from_what} does not fit within a length of {how_long} bits.")
    if how_much > how_long:
        raise ValueError(
            f"It does not make sense that {how_much} (how_much) > {how_long} (how_long)"
        )
    full_mask = (1 << how_long) - 1
    b_mask = (1 << (how_long - how_much)) - 1
    b_mask = (~b_mask) & full_mask
    return (from_what & b_mask) >> (how_long - how_much)


def extract_lower(from_what: int, how_much: int, how_long: int):
    """
    Extracts and returns the lower `how_much` bits from `from_what`.
    `from_what` is assumed to be `how_long` bits long.
    If `from_what` could not possibly be `how_long` bits long,
    ValueError is raised.
    If `how_much > how_long`, then for obvious reasons ValueError
    is raised again.
    Ex. `extract_upper(0b1101010010, 5, 12) == 0b10010`.
    `extract_upper(0b10000010, 1, 2) -> ValueError`
    """
    if from_what >= (1 << how_long):
        raise ValueError(f"{from_what} does not fit within a length of {how_long} bits.")
    if how_much > how_long:
        raise ValueError(
            f"It does not make sense that {how_much} (how_much) > {how_long} (how_long)"
        )
    return ((1 << how_much) - 1) & from_what
