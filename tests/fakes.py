# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared hardware-free VISA test doubles."""

from unittest.mock import MagicMock

import pyvisa
from pyvisa.resources import MessageBasedResource

from dp800 import DP800


class FakeResource(MessageBasedResource):
    """Exercise attribute configuration and I/O without a VISA backend."""

    encoding = "utf-8"
    read_termination = None
    write_termination = "\r\n"
    timeout = 2000
    query_delay = 0.0

    def __init__(self):
        self._session = None
        self.commands = []
        self.io_events = []
        self.error_queries = []
        self.error_query_delays = []
        self.queued_errors = []
        self.diagnostic_error = None
        self.errors_after_write = {}
        self.errors_after_query = {}
        self.responses = {"*IDN?": "RIGOL,DP832,serial,version"}
        self.write_errors = {}
        self.query_error = None
        self.close_error = None
        self.closed = 0
        self.on_io = lambda: None

    def write(self, command):
        self.on_io()
        self.io_events.append(command)
        self.commands.append(command)
        if command in self.write_errors:
            raise self.write_errors[command]
        self.queued_errors.extend(self.errors_after_write.get(command, []))
        return len(command)

    def query(self, command, delay=None):
        self.on_io()
        self.io_events.append(command)
        if command == ":SYST:ERR?":
            self.error_queries.append(self.timeout)
            self.error_query_delays.append(delay)
        else:
            self.commands.append(command)
        if self.query_error is not None:
            raise self.query_error
        if command == ":SYST:ERR?":
            if self.diagnostic_error is not None:
                raise self.diagnostic_error
            return self.queued_errors.pop(0) if self.queued_errors else '0,"No error"'
        self.queued_errors.extend(self.errors_after_query.get(command, []))
        return self.responses[command]

    def close(self):
        self.closed += 1
        if self.close_error is not None:
            raise self.close_error


def make_fake_visa():
    """Create an independent driver, resource, and manager for a test."""
    driver = DP800()
    resource = FakeResource()
    manager = MagicMock(spec=pyvisa.ResourceManager)
    manager.open_resource.return_value = resource

    def open_resource(resource_name, **kwargs):
        opened = manager.open_resource.return_value
        for key, value in kwargs.items():
            if key not in ("access_mode", "open_timeout", "resource_pyclass"):
                setattr(opened, key, value)
        return opened

    manager.open_resource.side_effect = open_resource
    return driver, resource, manager
