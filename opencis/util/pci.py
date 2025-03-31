"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""


def create_bdf(bus: int, device: int, function: int) -> int:
    """
    Creates a PCI express BDF integer from bus, device, and function values.

    Args:
    - bus (int): The bus value.
    - device (int): The device (or number) value.
    - function (int): The function value.

    Returns:
    - int: The BDF represented as a 16-bit integer.
    """
    return (bus << 8) | (device << 3) | function


def bdf_to_string(bdf: int) -> str:
    """
    Converts a PCI express BDF 16-bit integer into its string representation.

    Args:
    - bdf (int): The BDF represented as a 16-bit integer.

    Returns:
    - str: The BDF string in the format "bus:device.function".
    """
    bus = (bdf >> 8) & 0xFF
    device = (bdf >> 3) & 0x1F
    function = bdf & 0x07

    return f"{bus:02x}:{device:02x}.{function:x}"


def extract_device_from_bdf(bdf: int) -> int:
    """
    Extracts the device number from a PCI express BDF 16-bit integer.

    Args:
    - bdf (int): The BDF represented as a 16-bit integer.

    Returns:
    - int: The device number.
    """
    return (bdf >> 3) & 0x1F


def extract_bus_from_bdf(bdf: int) -> int:
    """
    Extracts the bus number from a PCI express BDF 16-bit integer.

    Args:
    - bdf (int): The BDF represented as a 16-bit integer.

    Returns:
    - int: The bus number.
    """
    return (bdf >> 8) & 0xFF


def extract_function_from_bdf(bdf: int) -> int:
    """
    Extracts the function number from a PCI express BDF 16-bit integer.

    Args:
    - bdf (int): The BDF represented as a 16-bit integer.

    Returns:
    - int: The function number.
    """
    return bdf & 0x07


def generate_bdfs_for_bus(bus: int) -> list[int]:
    """
    Generates all possible BDFs for a given bus number.

    Args:
    - bus (int): The bus number.

    Returns:
    - list[int]: A list of 16-bit integers representing all possible BDFs for the given bus number.
    """
    bdfs = []

    for device in range(0x20):  # Device can range from 0x00 to 0x1F
        for function in range(0x8):  # Function can range from 0x0 to 0x7
            bdf = (bus << 8) | (device << 3) | function
            bdfs.append(bdf)

    return bdfs
