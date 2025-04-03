"""
 Copyright (c) 2025, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import atexit
from functools import partial
import os
import sys


def get_memory_bin_name(index_primary: int = 0, index_secondary: int = -1) -> str:
    def cleanup(path):
        try:
            os.remove(path)
        except Exception:
            pass

    # Get caller function name
    # pylint: disable=protected-access
    func_name = sys._getframe(1).f_code.co_name

    while True:
        if index_secondary != -1:
            bin_name = f"mem_{func_name}_{index_primary}-{index_secondary}.bin"
        else:
            bin_name = f"mem_{func_name}_{index_primary}.bin"
        # Check if the bin name already exists
        if not os.path.exists(bin_name):
            break
        index_primary += 1

    # Make sure we remove it upon exit
    atexit.register(partial(cleanup, bin_name))
    return bin_name
