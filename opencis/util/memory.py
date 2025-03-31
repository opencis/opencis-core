"""
 Copyright (c) 2025, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import atexit
from functools import partial
import os
import sys


def get_memory_bin_name(index: int = 0) -> str:
    def cleanup(path):
        try:
            os.remove(path)
        except Exception:
            pass

    # Get caller function name
    # pylint: disable=protected-access
    func_name = sys._getframe(1).f_code.co_name

    while True:
        index += 1
        bin_name = f"mem_{func_name}_{index}.bin"
        # Check if the bin name already exists
        if not os.path.exists(bin_name):
            break

    # Make sure we remove it upon exit
    atexit.register(partial(cleanup, bin_name))
    return bin_name
