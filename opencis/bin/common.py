"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import click

from opencis.util.logger import logger


class BasedInt(click.ParamType):
    def convert(self, value, param, ctx):
        if isinstance(value, int):
            return value
        try:
            if value[:2].lower() == "0x":
                return int(value[2:], 16)
            return int(value, 10)
        except ValueError:
            logger.error(f"{value!r} is not a valid integer")
        return None


BASED_INT = BasedInt()
