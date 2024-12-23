"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

import logging
import datetime
import sys
from os import getcwd, makedirs
from os.path import join, dirname, exists


class MyLogger(logging.getLoggerClass()):
    def __init__(self):
        super().__init__(name="mylogger")
        self._name_to_level = logging.getLevelNamesMapping()
        self._stdout_hdlr = logging.StreamHandler(sys.stdout)

        # reset root logger log level
        logging.getLogger().setLevel(logging.NOTSET)

        # init stdout with defaults
        self.set_stdout_levels()

    def _get_formatter(self, show_timestamp: bool, show_loglevel: bool, show_linenumber: bool):
        headers = []
        if show_loglevel:
            headers.append("%(levelname)-5s")
        if show_timestamp:
            headers.append("%(relativeCreated)-4d")
        h_fmt = ""
        if headers:
            for h in headers[:-1]:
                h_fmt += h + ","
            h_fmt += headers[-1]

        m_fmt = "%(message)s"
        if show_linenumber:
            m_fmt += "(%(filename)s:%(lineno)d)"

        if h_fmt:
            fmt = h_fmt + " | " + m_fmt
        else:
            fmt = m_fmt
        formatter = logging.Formatter(fmt)
        return formatter

    def add_log_level(self, level_name: str, level_num: int):
        method_name = level_name.lower()

        def log(self, message, *args, **kwargs):
            self.log(level_num, message, *args, **kwargs)

        logging.addLevelName(level_num, level_name)
        setattr(logging, level_name, level_num)
        setattr(logging.getLoggerClass(), method_name, log)
        setattr(logging, method_name, log)
        self._name_to_level = logging.getLevelNamesMapping()

    def set_stdout_levels(
        self,
        loglevel: str = "INFO",
        show_timestamp: bool = False,
        show_loglevel: bool = False,
        show_linenumber: bool = False,
    ):
        formatter = self._get_formatter(show_timestamp, show_loglevel, show_linenumber)
        self.removeHandler(self._stdout_hdlr)
        self._stdout_hdlr.setLevel(self._name_to_level[loglevel])
        self._stdout_hdlr.setFormatter(formatter)
        self.addHandler(self._stdout_hdlr)

    def create_log_file(
        self,
        filename: str,
        loglevel: str = "DEBUG",
        show_timestamp: bool = False,
        show_loglevel: bool = False,
        show_linenumber: bool = False,
    ):
        # Create log directory
        filepath = join(getcwd(), filename)
        log_dir = dirname(filepath)
        if not exists(log_dir):
            makedirs(log_dir)

        formatter = self._get_formatter(show_timestamp, show_loglevel, show_linenumber)
        file_handler = logging.FileHandler(filename)
        file_handler.setLevel(self._name_to_level[loglevel])
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    def hexdump(self, loglevel, data, *args, **kwargs):
        addr = 0
        num_lines = (len(data) // 0x10) + 1
        for _ in range(num_lines):
            d = data[addr : addr + 0x10]
            if not d:
                return
            # non-printable ascii values to '.'
            data_ascii = "".join([chr(b) if (32 < b < 128) else "." for b in d])
            data_bytes = " ".join(f"{i:02x}" for i in d)
            line = f"{addr:08x}:  {data_bytes:47}  |{data_ascii:16}|"
            self._log(self._name_to_level[loglevel], line, args, **kwargs)
            addr += 0x10


# initialize logger and add log-level "TRACE"
logger = MyLogger()
TRACE = logging.DEBUG - 5
logger.add_log_level("TRACE", TRACE)

now = datetime.datetime.now()
logger.debug(f"Starting Timestamp: {now}")
