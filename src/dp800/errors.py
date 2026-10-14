# SPDX-License-Identifier: GPL-3.0-or-later

"""SCPI error-queue parsing and diagnostics."""

import re
from collections.abc import Sequence
from time import monotonic

from pyvisa.resources import MessageBasedResource

_ERROR_RESPONSE = re.compile(r'([+-]?\d+)\s*,\s*"((?:[^"]|"")*)"')
_MAX_ERROR_READS = 100


class InstrumentError(RuntimeError):
    """Instrument-reported errors observed after a command.

    Parameters
    ----------
    command : str
        Command associated with the error-queue check.
    errors : sequence of tuple of int and str
        Error codes and messages drained from the instrument's queue.
    """

    def __init__(self, command: str, errors: Sequence[tuple[int, str]]) -> None:
        """Store the command and immutable error entries.

        Parameters
        ----------
        command : str
            Command associated with the error-queue check.
        errors : sequence of tuple of int and str
            Error codes and messages returned by the instrument.
        """
        self.command = command
        self.errors = tuple(errors)
        details = "; ".join(f"{code}: {message}" for code, message in self.errors)
        super().__init__(f"Instrument errors after {command!r}: {details}")


def _read_error(
    resource: MessageBasedResource, *, delay: float | None = None
) -> tuple[int, str]:
    """Read one queue entry using direct VISA I/O to avoid recursive checks.

    Parameters
    ----------
    resource : MessageBasedResource
        Connected VISA resource.
    delay : float, optional
        Delay between writing and reading the query. Omit to use the resource's
        configured delay; deadline-limited diagnostics use zero.

    Returns
    -------
    error : tuple of int and str
        Error code and message; code zero indicates an empty queue.
    """
    response = resource.query(":SYST:ERR?", delay=delay).strip()
    match = _ERROR_RESPONSE.fullmatch(response)
    if match is None:
        raise ValueError(f"Invalid instrument error response: {response!r}.")
    return int(match[1]), match[2].replace('""', '"')


def _drain_errors(
    resource: MessageBasedResource, *, timeout_ms: float | None = None
) -> list[tuple[int, str]]:
    """Drain errors until the zero-code response, with a finite read limit.

    An optional total deadline bounds best-effort diagnostics after timeouts.
    The original resource timeout is restored even if diagnostics fail.

    Parameters
    ----------
    resource : MessageBasedResource
        Connected VISA resource.
    timeout_ms : float, optional
        Total diagnostic time budget in milliseconds. Omit to retain the
        configured resource timeout for each queue read.

    Returns
    -------
    errors : list of tuple of int and str
        Nonzero error codes and messages removed from the queue.
    """
    errors: list[tuple[int, str]] = []
    original_timeout = resource.timeout
    deadline = None if timeout_ms is None else monotonic() + timeout_ms / 1000
    try:
        for _ in range(_MAX_ERROR_READS):
            if deadline is not None:
                remaining_ms = (deadline - monotonic()) * 1000
                if remaining_ms <= 0:
                    raise TimeoutError(
                        "Instrument error diagnostics exceeded the deadline."
                    )
                resource.timeout = min(original_timeout, remaining_ms)
            code, message = _read_error(
                resource, delay=0.0 if deadline is not None else None
            )
            if deadline is not None and monotonic() > deadline:
                raise TimeoutError(
                    "Instrument error diagnostics exceeded the deadline."
                )
            if code == 0:
                return errors
            errors.append((code, message))
        raise RuntimeError("Instrument error queue did not empty within 100 reads.")
    finally:
        if deadline is not None:
            resource.timeout = original_timeout


def _check_errors(resource: MessageBasedResource, command: str) -> None:
    """Raise an InstrumentError if the instrument's queue contains errors.

    Parameters
    ----------
    resource : MessageBasedResource
        Connected VISA resource.
    command : str
        Command associated with the error-queue check.
    """
    errors = _drain_errors(resource)
    if errors:
        raise InstrumentError(command, errors)
