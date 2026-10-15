# SPDX-License-Identifier: GPL-3.0-or-later

"""Rigol DP800 series power supply control library.

The full instrument manual, including the programming guide, can be found at
https://www.rigolna.com/products/dc-power-loads/dp800/.
"""

import csv
import logging
import re
import warnings
from collections.abc import Mapping
from types import MappingProxyType, TracebackType
from typing import Any, Final, Literal

import pyvisa
from pyvisa.resources import MessageBasedResource, Resource

from .channel import DP800Channel

# Fixed SCPI framing: serial interfaces use the guide's CRLF end marker.
ENCODING: Final = "ascii"
WRITE_TERMINATION: Final = "\n"
READ_TERMINATION: Final = "\n"
SERIAL_TERMINATION: Final = "\r\n"
PROTOCOL_RESOURCE_SETTINGS: Final = MappingProxyType(
    {
        "encoding": ENCODING,
        "write_termination": WRITE_TERMINATION,
        "read_termination": READ_TERMINATION,
    }
)
SERIAL_PROTOCOL_RESOURCE_SETTINGS: Final = MappingProxyType(
    {
        "encoding": ENCODING,
        "write_termination": SERIAL_TERMINATION,
        "read_termination": SERIAL_TERMINATION,
    }
)

NOT_CONNECTED_MESSAGE: Final = "Instrument is not connected."
_MODEL_CHANNELS: Final = MappingProxyType(
    {"DP811": 1, "DP813": 1, "DP821": 2, "DP822": 2, "DP831": 3, "DP832": 3}
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class InstrumentError(RuntimeError):
    """Raw error-queue responses reported by the instrument."""


def _protocol_settings(resource_name: str) -> Mapping[str, str]:
    """Choose the guide's CRLF framing for full ASRL names, LF otherwise."""
    if resource_name.upper().startswith("ASRL"):
        return SERIAL_PROTOCOL_RESOURCE_SETTINGS
    return PROTOCOL_RESOURCE_SETTINGS


def _token(value: str) -> str:
    """Encode one unquoted SCPI token without permitting command chaining."""
    if not value or any(char in value for char in ',;\r\n"'):
        raise ValueError("Expected one SCPI token.")
    return value


def _quote(value: str) -> str:
    """Encode an ASCII SCPI string, escaping embedded quotation marks."""
    value.encode("ascii")
    if "\r" in value or "\n" in value:
        raise ValueError("SCPI strings cannot contain line terminators.")
    return '"' + value.replace('"', '""') + '"'


def _fields(response: str) -> list[str]:
    """Parse a comma-separated SCPI response, including quoted fields."""
    return next(csv.reader([response.strip()], skipinitialspace=True))


def _number(response: str) -> float:
    """Parse a numeric response with an optional physical-unit suffix."""
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*(?:V|A|W|S)?\s*",
        response,
        re.IGNORECASE,
    )
    if match is None:
        raise ValueError(f"Invalid numeric response: {response!r}")
    return float(match.group(1))


def _enabled(response: str) -> bool:
    """Parse a SCPI boolean; reject unexpected responses rather than hiding them."""
    value = response.strip().upper()
    if value in ("ON", "1", "YES"):
        return True
    if value in ("OFF", "0", "NO"):
        return False
    raise ValueError(f"Invalid boolean response: {response!r}")


def _block(response: str) -> str:
    """Remove a definite-length ASCII block header and verify its byte length."""
    if not response.startswith("#"):
        return response.strip()
    if len(response) < 2 or not response[1].isdigit() or response[1] == "0":
        raise ValueError("Expected a definite-length ASCII block.")
    digits = int(response[1])
    end = 2 + digits
    size_text = response[2:end]
    if len(size_text) != digits or not size_text.isdigit():
        raise ValueError("Invalid ASCII block length header.")
    size = int(size_text)
    payload = response[end : end + size]
    if len(payload.encode("ascii")) != size or response[end + size :].strip():
        raise ValueError("ASCII block length does not match payload.")
    return payload


def _source(command: str, channel: int | None) -> str:
    """Address a physical source or the currently selected source."""
    return (f":SOUR{channel}" if channel is not None else "") + command


def _limit_args(limit: Literal["MIN", "MAX"] | None) -> str:
    """Format an optional documented bound selector."""
    if limit is not None and limit not in ("MIN", "MAX"):
        raise ValueError("limit must be MIN or MAX.")
    return f" {limit}" if limit is not None else ""


class DP800:
    """Rigol DP800 series power supply instrument.

    Use connect() to initialize a connection and disconnect() to release it.
    A with block returns this instance and disconnects it on exit. Entering
    the block does not connect automatically.
    The VISA resource is held internally as _instr.
    """

    def __init__(self) -> None:
        """Initialize a disconnected DP800 driver."""
        self._instr: MessageBasedResource | None = None
        self._channels = {channel: DP800Channel(self, channel) for channel in (1, 2, 3)}

    def __enter__(self) -> "DP800":
        """Return this instance without opening a connection.

        Returns
        -------
        value : DP800
            This driver instance.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Disconnect on exit without suppressing exceptions from the block.

        Parameters
        ----------
        exc_type : type[BaseException] or None
            Type of exception raised by the block, or None for normal completion.
        exc_value : BaseException or None
            Exception raised by the block, or None for normal completion.
        traceback : TracebackType or None
            Exception traceback, or None for normal completion.
        """
        self.disconnect()

    # --- Connection lifecycle ---

    def connect(
        self,
        resource_name: str,
        *,
        resource_manager: pyvisa.ResourceManager | None = None,
        **resource_kwargs: Any,
    ) -> None:
        """Open and initialize a connection without resetting the instrument.

        The resource is assigned to _instr before stale errors are read and
        cleared. A failure clears _instr and closes the resource. Call
        set_remote() explicitly if remote mode is desired. Read identity
        explicitly if identification is required; connection logging is left
        to the caller.
        The instance stays disconnected on failure. PyVISA handles cleanup if
        open_resource() raises; the driver closes the returned resource if
        subsequent initialization fails.
        No reset, voltage/current setting, or output-enable command is sent.
        PyVISA can reuse a manager for the same backend. This driver closes only
        its instrument resource. The PyVISA resource retains its manager for
        the connection's lifetime.

        Parameters
        ----------
        resource_name : str
            Full VISA resource name, e.g. "ASRL2::INSTR", "GPIB0::14::INSTR" etc. See
            https://pyvisa.readthedocs.io/en/latest/introduction/names.html for more
            info on correct formatting for resource names.
        resource_manager : pyvisa.ResourceManager, optional
            Manager to use for this connection. A supplied manager
            remains caller-owned and is never closed by this driver. Otherwise,
            a manager is obtained lazily. The driver never explicitly closes
            managers; their lifecycle is handled by PyVISA or the caller.
        resource_kwargs : dict
            VISA opening options (access_mode, open_timeout, resource_pyclass)
            and resource attributes such as timeout, passed directly to
            PyVISA for validation and configuration. This driver uses
            ASCII encoding and LF ("\\n") read/write termination; full ASRL
            serial resource names use CRLF ("\\r\\n"). Conflicting
            values for these driver-owned attributes emit a warning and are
            ignored in favor of the constants. Other attributes use VISA
            defaults unless supplied here. Call reset() explicitly after
            connecting if required.

        Raises
        ------
        RuntimeError
            If already connected. Disconnect before connecting again.
        ValueError
            If an invalid resource attribute is supplied.
        TypeError
            If the opened resource is not message-based.
        """
        if self._instr is not None:
            raise RuntimeError("Already connected; disconnect before reconnecting.")
        protocol_settings = _protocol_settings(resource_name)
        for key, required in protocol_settings.items():
            if key in resource_kwargs and resource_kwargs[key] != required:
                warnings.warn(
                    f"The driver owns {key}; the supplied value "
                    f"{resource_kwargs[key]!r} will be ignored. Using {required!r}.",
                    stacklevel=2,
                )
        resource_kwargs.update(protocol_settings)
        manager = (
            pyvisa.ResourceManager() if resource_manager is None else resource_manager
        )
        resource: Resource | None = None
        try:
            resource = manager.open_resource(resource_name, **resource_kwargs)
            if not isinstance(resource, MessageBasedResource):
                raise TypeError("DP800 requires a message-based VISA resource.")
            self._instr = resource
            self.get_errors()
        except BaseException:
            self._instr = None
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    logger.warning(
                        "Failed to close instrument during initialization cleanup.",
                        exc_info=True,
                    )
            raise

    def disconnect(self) -> None:
        """Disable outputs, return to local mode, and release the connection.

        Already disconnected instances are a no-op. Identity is read at shutdown
        to address only physical outputs on known models. If discovery fails or
        the model is unknown, all three outputs are attempted. No channel count
        is retained. All output-disable commands and local mode are attempted
        even if one fails. The resource
        is then closed, and _instr is cleared even if cleanup fails. The driver
        does not explicitly close the manager. The first error is
        re-raised after cleanup; subsequent errors are logged.
        """
        resource = self._instr
        if resource is None:
            return
        error: Exception | None = None
        try:
            channel_count = 3
            try:
                model = self.identity[1].strip().upper().removesuffix("A")
                channel_count = _MODEL_CHANNELS.get(model, 3)
            except Exception:
                logger.debug(
                    "Could not identify outputs during shutdown; attempting all three.",
                    exc_info=True,
                )
            commands = [
                f":OUTP  CH{channel},OFF" for channel in range(1, channel_count + 1)
            ]
            for command in [*commands, ":SYST:LOC"]:
                try:
                    self._write(command)
                except Exception as exc:
                    if error is None:
                        error = exc
                    else:
                        logger.warning(
                            "Additional disconnect error for command %r.",
                            command,
                            exc_info=True,
                        )
        finally:
            self._instr = None
            try:
                resource.close()
            except Exception as exc:
                if error is None:
                    error = exc
                else:
                    logger.warning("Failed to close instrument.", exc_info=True)
        if error is not None:
            raise error

    # --- Channel views ---

    @property
    def channels(self) -> Mapping[int, DP800Channel]:
        """Read-only mapping of read/write channel views for numbers 1 - 3.

        Mapping entries cannot be replaced, but each channel's settings can be
        read and assigned. Objects survive reconnects and use the parent's current
        connection. Their presence does not guarantee the instrument supports
        that channel; unsupported commands are reported through the error queue.

        Returns
        -------
        value : Mapping[int, DP800Channel]
            Channel views keyed by one-based channel numbers.
        """
        return MappingProxyType(self._channels)

    # --- VISA I/O ---

    def _write(self, command: str) -> int:
        """Write a command and raise any errors reported by the instrument.

        A successful transport write is followed by error-queue draining. The
        command may have executed even if the subsequent diagnostic query fails.

        Parameters
        ----------
        command : str
            SCPI command to send to the instrument.

        Returns
        -------
        value : int
            Number of bytes written, as reported by PyVISA.
        """
        if self._instr is None:
            raise RuntimeError(NOT_CONNECTED_MESSAGE)
        count = self._instr.write(command)
        self._check_errors()
        return count

    def _query(self, command: str, *, check_errors: bool = True) -> str:
        """Read a query response, then check the instrument error queue.

        A VISA timeout triggers best-effort error diagnostics using the configured
        PyVISA timeout. Instrument errors are chained from the original timeout.
        Empty, malformed, or failed diagnostics preserve the original exception.
        This recovery attempt does not guarantee response synchronization.
        Set check_errors=False for error-queue queries to prevent recursion in
        both normal checking and timeout diagnostics.

        Parameters
        ----------
        command : str
            SCPI command to send to the instrument.
        check_errors : bool, optional
            Whether to inspect the error queue after a response or a timeout.
            Defaults to True; get_errors() disables it for its own queries.

        Returns
        -------
        value : str
            Response received from the instrument.
        """
        if self._instr is None:
            raise RuntimeError(NOT_CONNECTED_MESSAGE)
        try:
            response = self._instr.query(command)
        except pyvisa.errors.VisaIOError as original:
            if (
                not check_errors
                or original.error_code != pyvisa.constants.StatusCode.error_timeout
            ):
                raise
            try:
                errors = self.get_errors()
            except Exception:
                errors = []
            if errors:
                raise InstrumentError("\n".join(errors)) from original
            raise
        if check_errors:
            self._check_errors()
        return response

    def _check_errors(self) -> None:
        """Raise the raw instrument error responses if the queue is nonempty."""
        errors = self.get_errors()
        if errors:
            raise InstrumentError("\n".join(errors))

    # --- ANALyzer commands ---

    @property
    def analyzer_current_time(self) -> int:
        """Analyzer current time.

        Returns
        -------
        value : int
            analyzer current time.
        """
        response = self._query(":ANAL:CURRT?")
        return int(response)

    @analyzer_current_time.setter
    def analyzer_current_time(self, value: int) -> None:
        """Set analyzer current time.

        Parameters
        ----------
        value : int
            analyzer current time.
        """
        self._write(":ANAL:CURRT " + str(value))

    @property
    def analyzer_start_time(self) -> int:
        """Analyzer start time.

        Returns
        -------
        value : int
            analyzer start time.
        """
        response = self._query(":ANAL:STARTT?")
        return int(response)

    @analyzer_start_time.setter
    def analyzer_start_time(self, value: int | Literal["MIN", "MAX"]) -> None:
        """Set analyzer start time.

        Parameters
        ----------
        value : int or {"MIN", "MAX"}
            analyzer start time.
        """
        self._write(":ANAL:STARTT " + str(value))

    @property
    def analyzer_end_time(self) -> int:
        """Analyzer end time.

        Returns
        -------
        value : int
            analyzer end time.
        """
        response = self._query(":ANAL:ENDT?")
        return int(response)

    @analyzer_end_time.setter
    def analyzer_end_time(self, value: int | Literal["MIN", "MAX"]) -> None:
        """Set analyzer end time.

        Parameters
        ----------
        value : int or {"MIN", "MAX"}
            analyzer end time.
        """
        self._write(":ANAL:ENDT " + str(value))

    @property
    def analyzer_object(self) -> str:
        """Analyzer object.

        Returns
        -------
        value : str
            analyzer object.
        """
        response = self._query(":ANAL:OBJ?")
        return response.strip()

    @analyzer_object.setter
    def analyzer_object(self, value: str) -> None:
        """Set analyzer object.

        Parameters
        ----------
        value : str
            analyzer object.
        """
        self._write(":ANAL:OBJ " + _token(value))

    @property
    def analyzer_file(self) -> str:
        """Path of the opened recording, or NONE.

        Returns
        -------
        value : str
            Path of the opened recording, or NONE.
        """
        response = self._query(":ANAL:FILE?")
        return _fields(response)[0]

    @property
    def analyzer_results(self) -> dict[str, float]:
        """Statistics of the last analysis, keyed by instrument labels.

        Returns
        -------
        value : dict[str, float]
            Statistics of the last analysis, keyed by instrument labels.
        """
        response = self._query(":ANAL:RES?")
        return {
            field.partition(":")[0]: _number(field.partition(":")[2])
            for field in _fields(response)
        }

    def analyze(self) -> None:
        """Analyze the opened recording between the selected start and end times."""
        self._write(":ANAL:ANAL")

    def open_recording(self, location: int | str) -> None:
        """Open an internal recording slot or external recording path.

        Parameters
        ----------
        location : int or str
            Internal ROF slot 1–10, or external .ROF path.
        """
        self._write(
            f":ANAL:MEM {location}"
            if isinstance(location, int)
            else ":ANAL:MMEM " + _quote(location)
        )

    def get_recorded_values(self, time: int) -> tuple[float, float, float]:
        """Read recorded voltage, current and power at a time in seconds.

        Parameters
        ----------
        time : int
            Time within the opened recording, in seconds.

        Returns
        -------
        value : tuple[float, float, float]
            Read recorded voltage, current and power at a time in seconds.
        """
        fields = _fields(self._query(f":ANAL:VAL? {time}"))
        voltage, current, power = (_number(field.partition(":")[2]) for field in fields)
        return voltage, current, power

    # --- APPLy commands ---

    def set_apply(
        self,
        channel: int | None = None,
        voltage: float | Literal["MIN", "MAX", "DEF"] | None = None,
        current: float | Literal["MIN", "MAX", "DEF"] | None = None,
    ) -> None:
        """Select a channel and set its current and/or voltage.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, the currently selected channel will be used.
        voltage : float; 'MIN', 'MAX', or 'DEF'; optional
            Value to set the voltage of the selected channel to. 'MIN', 'MAX', and
            'DEF' denote the minimum, maximum, and default settings respectively.
        current : float; 'MIN', 'MAX', or 'DEF'; optional
            Value to set the current of the selected channel to. 'MIN', 'MAX', and
            'DEF' denote the minimum, maximum, and default settings respectively.
        """

        if current is not None and voltage is None:
            raise ValueError("A voltage is required when setting current with APPLy.")
        if channel is None and voltage is None:
            raise ValueError("Specify a channel or voltage.")
        values = [f"CH{channel}"] if channel is not None else []
        if voltage is not None:
            values.append(str(voltage))
        if current is not None:
            values.append(str(current))
        self._write(":APPL " + ",".join(values))

    def get_apply(
        self,
        channel: int | None = None,
        function: Literal["CURR", "VOLT"] | None = None,
    ) -> float | tuple[str, str, float, float]:
        """Get the voltage and/or current of the selected channel.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, the currently selected channel will be used.
        function : 'CURR' or 'VOLT', optional
            Function to query: current ('CURR') or voltage ('VOLT'). If both are
            omitted the query will return the channel range and both the current and
            voltage values.

        Returns
        -------
        resp : float or tuple
            If both `channel` and `function` are specified, the set value of the
            desired function is returned. If `function` is omitted, a tuple is returned
            comprised of the currently selected channel, its rated values, the set
            value of the voltage, and the set value of the current.
        """
        if function is not None and channel is None:
            raise ValueError("Specify a channel when querying an APPLy function.")
        command = ":APPL?" + (f" CH{channel}" if channel is not None else "")
        if function is not None:
            return _number(self._query(command + "," + _token(function)))
        ch, rating, voltage, current = _fields(self._query(command))
        return ch, rating, _number(voltage), _number(current)

    # --- DELAY commands ---

    def set_delay_cycles(
        self, finite: Literal["N", "I"], cycles: int | None = None
    ) -> None:
        """Set the number of cycles for the delayer.

        Parameters
        ----------
        finite : 'N' or 'I'
            Choose 'N' for a finite number of cycles specified by `cycles`. Choose 'I'
            for an infinite number of cycles.
        cycles : int, optional
            Number of delay cycles. Defaults to 1 if omitted. If `finite` is 'I' this
            parameter is ignored. Must be in range 1 - 99999.
        """
        cmd = f":DELAY:CYCLE {finite}"

        if (finite == "N") & (cycles is not None):
            cmd += f",{cycles}"

        self._write(cmd)

    def get_delay_cycles(self) -> str | tuple[str, int]:
        """Get the number of cycles for the delayer.

        Returns
        -------
        resp : str or tuple of str and int
            Formatted number of cycles for the delayer. Can be 'I' or tuple comprised of
            'N' and and integer representing the number of cycles.
        """
        cmd = ":DELAY:CYCLE?"
        resp = self._query(cmd).split(",")

        if len(resp) == 1:
            return resp[0]
        else:
            return resp[0], int(resp[1])

    @property
    def delay_end_state(self) -> str:
        """Get the state of the instrument when the delayer stops.

        Each read or assignment performs VISA I/O and can raise communication
        errors.

        Returns
        -------
        endstate : 'ON', 'OFF', 'LAST'
            State to put instrument in when delayer stops. 'ON' switches on the output,
            'OFF' switches off the output, and 'LAST' uses the last state.
        """
        cmd = ":DELAY:ENDS?"
        endstate = self._query(cmd)

        return endstate

    @delay_end_state.setter
    def delay_end_state(self, endstate: Literal["ON", "OFF", "LAST"]) -> None:
        """Set the state of the instrument when the delayer stops.

        Parameters
        ----------
        endstate : 'ON', 'OFF', 'LAST'
            State to put instrument in when delayer stops. 'ON' switches on the output,
            'OFF' switches off the output, and 'LAST' uses the last state.
        """
        cmd = f":DELAY:ENDS {endstate}"
        self._write(cmd)

    @property
    def delay_groups(self) -> int:
        """Get the number of output groups of the delayer.

        Each read or assignment performs VISA I/O and can raise communication
        errors.
        The instrument supports group counts in the range 1 - 2048.

        Returns
        -------
        groups : int
            Number of output groups of delayer cycles, i.e. number of times output
            turns on or off.
        """
        cmd = f":DELAY:GROUP?"
        groups = int(self._query(cmd))

        return groups

    @delay_groups.setter
    def delay_groups(self, groups: int) -> None:
        """Set the number of output groups of the delayer.

        Parameters
        ----------
        groups : int
            Number of output groups of delayer cycles, i.e. number of times output
            turns on or off. Must be in range 1-2048.
        """
        cmd = f":DELAY:GROUP {groups}"
        self._write(cmd)

    @property
    def delay_enabled(self) -> bool:
        """delay enabled.

        Returns
        -------
        value : bool
            delay enabled.
        """
        response = self._query(":DELAY?")
        return _enabled(response)

    @delay_enabled.setter
    def delay_enabled(self, value: bool) -> None:
        """Set delay enabled.

        Parameters
        ----------
        value : bool
            delay enabled.
        """
        self._write(":DELAY " + ("ON" if value else "OFF"))

    @property
    def delay_state_pattern(self) -> str:
        """delay state pattern.

        Returns
        -------
        value : str
            delay state pattern.
        """
        response = self._query(":DELAY:STAT:GEN?")
        return response.strip()

    @delay_state_pattern.setter
    def delay_state_pattern(self, value: str) -> None:
        """Set delay state pattern.

        Parameters
        ----------
        value : str
            delay state pattern.
        """
        self._write(":DELAY:STAT:GEN " + _token(value))

    def set_delay_parameters(self, index: int, enabled: bool, duration: int) -> None:
        """Set one delay entry for the selected channel.

        Parameters
        ----------
        index : int
            Zero-based entry number, 0–2047.
        enabled : bool
            Output state during the entry.
        duration : int
            Duration in seconds, 1–99999.
        """
        self._write(f':DELAY:PARA {index},{"ON" if enabled else "OFF"},{duration}')

    def get_delay_parameters(
        self, first: int = 0, count: int = 1
    ) -> list[tuple[int, bool, int]]:
        """Read delay entries for the selected channel.

        Parameters
        ----------
        first : int, optional
            First zero-based entry, default 0.
        count : int, optional
            Number of entries, default 1.

        Returns
        -------
        value : list[tuple[int, bool, int]]
            Read delay entries for the selected channel.
        """
        rows = _block(self._query(f":DELAY:PARA? {first},{count}"))
        return [
            (int(fields[0]), _enabled(fields[1]), int(fields[2]))
            for row in rows.split(";")
            if row.strip()
            for fields in [_fields(row)]
        ]

    @property
    def delay_stop_condition(self) -> tuple[str, float | None]:
        """Stop condition and optional voltage/current/power threshold.

        Returns
        -------
        value : tuple[str, float | None]
            Stop condition and optional voltage/current/power threshold.
        """
        response = self._query(":DELAY:STOP?")
        return (
            _fields(response)[0],
            _number(_fields(response)[1]) if len(_fields(response)) > 1 else None,
        )

    @delay_stop_condition.setter
    def delay_stop_condition(self, value: tuple[str, float | None]) -> None:
        """Set stop condition and optional voltage/current/power threshold.

        Parameters
        ----------
        value : tuple[str, float | None]
            Stop condition and optional voltage/current/power threshold.
        """
        self._write(
            ":DELAY:STOP "
            + _token(value[0])
            + (f",{value[1]}" if value[1] is not None else "")
        )

    @property
    def delay_time_method(self) -> tuple[str, int, int]:
        """Generation method and its two time parameters in seconds.

        Returns
        -------
        value : tuple[str, int, int]
            Generation method and its two time parameters in seconds.
        """
        response = self._query(":DELAY:TIME:GEN?")
        return (
            _fields(response)[0],
            int(_fields(response)[1]),
            int(_fields(response)[2]),
        )

    @delay_time_method.setter
    def delay_time_method(self, value: tuple[str, int, int]) -> None:
        """Set generation method and its two time parameters in seconds.

        Parameters
        ----------
        value : tuple[str, int, int]
            Generation method and its two time parameters in seconds.
        """
        self._write(":DELAY:TIME:GEN " + f"{_token(value[0])},{value[1]},{value[2]}")

    # --- DISPlay commands ---

    @property
    def display_mode(self) -> str:
        """Display mode NORMAL, WAVE, DIAL or CLASSIC.

        Returns
        -------
        value : str
            Display mode NORMAL, WAVE, DIAL or CLASSIC.
        """
        response = self._query(":DISP:MODE?")
        return response.strip()

    @display_mode.setter
    def display_mode(self, value: str) -> None:
        """Set display mode NORMAL, WAVE, DIAL or CLASSIC.

        Parameters
        ----------
        value : str
            Display mode NORMAL, WAVE, DIAL or CLASSIC.
        """
        self._write(":DISP:MODE " + _token(value))

    @property
    def display_enabled(self) -> bool:
        """Whether the display is enabled.

        Returns
        -------
        value : bool
            Whether the display is enabled.
        """
        response = self._query(":DISP?")
        return _enabled(response)

    @display_enabled.setter
    def display_enabled(self, value: bool) -> None:
        """Set whether the display is enabled.

        Parameters
        ----------
        value : bool
            Whether the display is enabled.
        """
        self._write(":DISP " + ("ON" if value else "OFF"))

    @property
    def display_text(self) -> str:
        """Custom display text.

        Returns
        -------
        value : str
            Custom display text.
        """
        response = self._query(":DISP:TEXT?")
        return _fields(response)[0]

    def set_display_text(
        self, text: str, x: int | None = None, y: int | None = None
    ) -> None:
        """Display ASCII text at optional screen coordinates.

        Parameters
        ----------
        text : str
            Up to 45 ASCII characters.
        x : int or None, optional
            Horizontal position, 0–320; instrument default if omitted.
        y : int or None, optional
            Vertical position, 0–240; instrument default if omitted.
        """
        if len(text) > 45:
            raise ValueError("Display text is limited to 45 characters.")
        if y is not None and x is None:
            raise ValueError("Specify x when specifying y.")
        command = ":DISP:TEXT " + _quote(text)
        if x is not None:
            command += f",{x}"
        if y is not None:
            command += f",{y}"
        self._write(command)

    def clear_display_text(self) -> None:
        """Clear custom display text."""
        self._write(":DISP:TEXT:CLE")

    # --- IEEE488.2 commands ---

    def clear_event_registers(self) -> None:
        """Clear all event registers."""
        self._write("*CLS")

    @property
    def standard_event_enable_register(self) -> int:
        """Get the standard event enable register value.

        Each read or assignment performs VISA I/O and can raise communication
        errors.

        Returns
        -------
        value : int
            Register bitmask in the range 0 - 255; assign to enable bits.
        """
        value = int(self._query("*ESE?"))

        return value

    @standard_event_enable_register.setter
    def standard_event_enable_register(self, value: int) -> None:
        """Enable bits in the standard event enable register.

        Parameters
        ----------
        value : int
            Decimal value of the enable register corresponding to the sum of binary
            weights of the bits to be enabled, e.g. to enable bits 1 and 3 only would
            require setting the value to 2^1 + 2^3 = 10. Must be in range 0 - 255.
        """
        if (value >= 0) & (value <= 255):
            self._write(f"*ESE {value}")
        else:
            raise ValueError(f"Value: {value} is out of range. Must be in range 0-255.")

    def get_standard_event_register(self) -> int:
        """Get the standard event register value.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self._query("*ESR?"))

        return value

    @property
    def identity(self) -> list[str]:
        """Get instrument identity string.

        Each access performs VISA I/O and can raise communication errors.

        Returns
        -------
        id : list of str
            List of identification strings consisting of manufacturer, model, serial
            number, and board version number in order.
        """
        idn = self._query("*IDN?").split(",")

        return idn

    def set_opc(self) -> None:
        """Set operation complete.

        Sets bit 0 of the standard event register after completing the current
        operation.
        """
        self._write("*OPC")

    def get_opc(self) -> int:
        """Query whether current operation is complete.

        Returns
        -------
        opc : int
            Binary value representing the completion state of the current command:

                * 0 : incomplete
                * 1 : complete
        """
        opc = int(self._query("*OPC?"))

        return opc

    @property
    def option_installation_status(self) -> str:
        """Get the status of installed options.

        Each access performs VISA I/O and can raise communication errors.

        Returns
        -------
        options : str
            List of options. If an option is installed its name is returned, otherwise
            the query returns a 0.
        """
        options = self._query("*OPT?")

        return options

    @property
    def power_on_status_clear_bit(self) -> int:
        """Get the power-on status clear bit.

        Each read or assignment performs VISA I/O and can raise communication
        errors.

        Returns
        -------
        value : int
            Value of power-on status clear bit. Values:

                * 0 : Cleared, status enable registers maintain values at power down.
                * 1 : Set, all status and enable registers are cleared on power up.
        """
        cmd = f"*PSC?"
        value = int(self._query(cmd))

        return value

    @power_on_status_clear_bit.setter
    def power_on_status_clear_bit(self, value: int) -> None:
        """Set the power-on status clear bit.

        Parameters
        ----------
        value : {0, 1}
            Value of power-on status clear bit. Values:

                * 0 : Cleared, status enable registers maintain values at power down.
                * 1 : Set, all status and enable registers are cleared on power up.
        """
        cmd = f"*PSC {value}"
        self._write(cmd)

    def recall_setup(self, number: int) -> None:
        """Recall instrument setup from setting buffer.

        Parameters
        ----------
        number : {1 - 10}
            Buffer number, 1 =< number =< 10.
        """
        cmd = f"*RCL {number}"
        self._write(cmd)

    def reset(self) -> None:
        """Reset the instrument to the factory default configuration."""
        cmd = f"*RST"
        self._write(cmd)

    def save_setup(self, number: int) -> None:
        """Save the instrument setup in a settings buffer.

        Parameters
        ----------
        number : {1 - 10}
            Buffer number, 1 =< number =< 10.
        """
        cmd = f"*SAV {number}"
        self._write(cmd)

    @property
    def status_byte_enable_register(self) -> int:
        """Get the status byte enable register value.

        Each read or assignment performs VISA I/O and can raise communication
        errors.

        Returns
        -------
        value : int
            Register bitmask in the range 0 - 255; assign to enable bits.
        """
        value = int(self._query("*SRE?"))

        return value

    @status_byte_enable_register.setter
    def status_byte_enable_register(self, value: int) -> None:
        """Enable bits in the status byte enable register.

        Parameters
        ----------
        value : int
            Decimal value of the enable register corresponding to the sum of binary
            weights of the bits to be enabled, e.g. to enable bits 1 and 3 only would
            require setting the value to 2^1 + 2^3 = 10. Must be in range 0 - 255.
        """
        if (value >= 0) & (value <= 255):
            self._write(f"*SRE {value}")
        else:
            raise ValueError(f"Value: {value} is out of range. Must be in range 0-255.")

    @property
    def status_byte_register(self) -> int:
        """Get the status byte register value.

        Querying this register does not clear it.

        Each access performs VISA I/O and can raise communication errors.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self._query("*STB?"))

        return value

    def trigger(self) -> None:
        """Generate a trigger.

        Only available when bus (software) trigger is selected.
        """
        self._write("*TRG")

    @property
    def self_test_results(self) -> list[str]:
        """Get the results of the instrument self-test.

        Each access performs VISA I/O and can raise communication errors.

        Returns
        -------
        result : list
            List of test results for the top board, bottom board, and fan.
        """
        result = self._query("*TST?").split(",")

        return result

    def wait(self) -> None:
        """Wait until processing all pending commands is complete."""
        self._write("*WAI")

    # --- INITiate commands ---

    def init_trigger(self) -> None:
        """Initialise the trigger system."""
        cmd = ":INIT"
        self._write(cmd)

    # --- INSTrument commands ---

    @property
    def trigger_coupling_channels(self) -> str | list[str]:
        """Get trigger coupling channels.

        Only applicable to multi-channel models.

        Each read or assignment performs VISA I/O and can raise communication
        errors.
        Assign "ALL", "NONE", or a list of at least two channel names.

        Returns
        -------
        channels : str or list
            If 'ALL' or 'NONE' that string is returned. Otherwise query returns a list
            where each element is a channel name and rating separated by a `:`.
        """
        channels = self._query(":INST:COUP?").split(",")
        if len(channels) == 1:
            return channels[0]

        return channels

    @trigger_coupling_channels.setter
    def trigger_coupling_channels(self, channels: str | list[str]) -> None:
        """Set trigger coupling channels.

        Only applicable to multi-channel models.

        Parameters
        ----------
        channels : 'ALL', 'NONE', or list containing 'CH1', 'CH2', 'CH3'
            Trigger coupling channels. If list, should contain at least two channels.
        """
        cmd = ":INST:COUP "
        cmd += ",".join(channels) if isinstance(channels, list) else channels
        self._write(cmd)

    @property
    def selected_channel(self) -> int:
        """Get the currently selected channel.

        Only applicable to multi-channel models.

        The instrument provides two functions for this: NSELct and SELect. NSELect
        returns a bare number, e.g. 2, whereas SELect returns a channel name and
        rated output. This method always uses NSELect because fewer characters are
        exchanged in the query operation.

        Each read or assignment performs VISA I/O and can raise communication
        errors.
        Assigning selects the channel used by subsequent commands that omit a
        channel argument. Only multi-channel models support this property.

        Returns
        -------
        channel : int
            Currently selected channel number.
        """
        channel = int(self._query(":INST:NSEL?"))

        return channel

    @selected_channel.setter
    def selected_channel(self, channel: int) -> None:
        """Select the current channel.

        Only applicable to multi-channel models.

        The instrument provides two functions for this: NSELct and SELect. NSELect
        uses a bare number, e.g. 2, whereas SELect requires 'CH' be prepended. This
        method always uses SELect (omitting redundant ":SEL") because it requires
        fewer characters to be sent to the instrument.

        Parameters
        ----------
        channel : int
            Channel number.
        """
        self._write(f":INST CH{channel}")

    # --- LIC commands ---

    def install_options(self, options_licence: str) -> None:
        """Install options.

        Only applicable to DP831/DP832/DP821/DP811.

        Parameters
        ----------
        options_licence : str
            Unique 28-byte ASCII string only including English letters and numbers.
        """
        self._write(f":LIC:SET {options_licence}")

    # --- MEASure commands ---

    def measure(
        self,
        func: Literal["ALL", "CURR", "POWE", "VOLT"] | None = None,
        channel: int | None = None,
    ) -> str | list[str]:
        """Read the voltage, current, and/or power of a channel.

        Parameters
        ----------
        func : 'ALL', 'CURR', 'POWE', 'VOLT'; optional
            Function to measure. 'ALL' measures all functions. If omitted, measures voltage.
        channel : int, optional
            Channel to read. If not given, the query will return the measurement for
            the currently selected channel.

        Returns
        -------
        values : str or list of str
            Measurement response string(s), without numeric conversion.
        """
        cmd = f":MEAS"
        if func is not None:
            cmd += f":{func}"
        cmd += "?"
        if channel is not None:
            cmd += f" CH{channel}"
        values = self._query(cmd).split(",")
        if len(values) == 1:
            return values[0]

        return values

    # --- MEMory commands ---

    def save_file(self, file_type: str, location: int | str) -> None:
        """Save a state/timer/delay file in internal or external storage.

        Parameters
        ----------
        file_type : str
            RSF (state), RTF (timer) or RDF (delay). External paths use their suffix.
        location : int or str
            Internal slot 1–10 or external filename.
        """
        if file_type not in ("RSF", "RTF", "RDF"):
            raise ValueError("file_type must be RSF, RTF or RDF.")
        if isinstance(location, str) and not location.upper().endswith("." + file_type):
            raise ValueError("External filename suffix must match file_type.")
        if isinstance(location, int):
            self._write(f":MEM:STOR {_token(file_type)},{location}")
        else:
            self._write(":MMEM:STOR " + _quote(location))

    def recall_file(self, file_type: str, location: int | str) -> None:
        """Recall a state/timer/delay file in internal or external storage.

        Parameters
        ----------
        file_type : str
            RSF (state), RTF (timer) or RDF (delay). External paths use their suffix.
        location : int or str
            Internal slot 1–10 or external filename.
        """
        if file_type not in ("RSF", "RTF", "RDF"):
            raise ValueError("file_type must be RSF, RTF or RDF.")
        if isinstance(location, str) and not location.upper().endswith("." + file_type):
            raise ValueError("External filename suffix must match file_type.")
        if isinstance(location, int):
            self._write(f":MEM:LOAD {_token(file_type)},{location}")
        else:
            self._write(":MMEM:LOAD " + _quote(location))

    def delete_memory_file(self, file_type: str, slot: int) -> None:
        """Delete an internal state, recording, timer or delay file.

        Parameters
        ----------
        file_type : str
            RSF, ROF, RTF or RDF.
        slot : int
            Internal slot 1–10.
        """
        self._write(f":MEM:DEL {_token(file_type)},{slot}")

    def set_memory_lock(self, file_type: str, slot: int, enabled: bool) -> None:
        """Lock or unlock an internal file.

        Parameters
        ----------
        file_type : str
            RSF, ROF, RTF or RDF.
        slot : int
            Internal slot 1–10.
        enabled : bool
            Whether to lock the file.
        """
        self._write(
            f':MEM:LOCK {_token(file_type)},{slot},{"ON" if enabled else "OFF"}'
        )

    def get_memory_lock(self, file_type: str, slot: int) -> bool:
        """Query whether an internal file is locked.

        Parameters
        ----------
        file_type : str
            RSF, ROF, RTF or RDF.
        slot : int
            Internal slot 1–10.

        Returns
        -------
        value : bool
            Query whether an internal file is locked.
        """
        return _enabled(self._query(f":MEM:LOCK? {_token(file_type)},{slot}"))

    def memory_file_exists(self, file_type: str, slot: int) -> bool:
        """Query whether an internal file exists.

        Parameters
        ----------
        file_type : str
            RSF, ROF, RTF or RDF.
        slot : int
            Internal slot 1–10.

        Returns
        -------
        value : bool
            Query whether an internal file exists.
        """
        return _enabled(self._query(f":MEM:VAL? {_token(file_type)},{slot}"))

    # --- MMEMory commands ---

    @property
    def directory(self) -> str:
        """Current external working directory.

        Returns
        -------
        value : str
            Current external working directory.
        """
        response = self._query(":MMEM:CDIR?")
        return _fields(response)[0]

    @directory.setter
    def directory(self, value: str) -> None:
        """Set current external working directory.

        Parameters
        ----------
        value : str
            Current external working directory.
        """
        self._write(":MMEM:CDIR " + _quote(value))

    @property
    def directory_entries(self) -> list[str]:
        """Files and directories in the current external directory.

        Returns
        -------
        value : list[str]
            Files and directories in the current external directory.
        """
        response = self._query(":MMEM:CAT?")
        return _fields(response) if response.strip() else []

    @property
    def available_disks(self) -> list[str]:
        """Available external drive names.

        Returns
        -------
        value : list[str]
            Available external drive names.
        """
        response = self._query(":MMEM:DISK?")
        return _fields(response) if response.strip() else []

    def make_directory(self, path: str) -> None:
        """Create an external directory.

        Parameters
        ----------
        path : str
            External directory or file path.
        """
        self._write(":MMEM:MDIR " + _quote(path))

    def delete_file(self, path: str) -> None:
        """Delete an external file.

        Parameters
        ----------
        path : str
            External directory or file path.
        """
        self._write(":MMEM:DEL " + _quote(path))

    # --- MONItor commands ---

    @property
    def monitor_voltage(self) -> float:
        """Monitor voltage threshold.

        Returns
        -------
        value : float
            Monitor voltage threshold.
        """
        response = self._query(":MONI:VOLT?")
        return _number(response)

    @monitor_voltage.setter
    def monitor_voltage(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set monitor voltage threshold.

        Parameters
        ----------
        value : float or {"MIN", "MAX"}
            Monitor voltage threshold.
        """
        self._write(":MONI:VOLT " + str(value))

    @property
    def monitor_voltage_condition(self) -> tuple[str, str]:
        """Voltage comparison and AND/OR/NONE relation.

        Returns
        -------
        value : tuple[str, str]
            Voltage comparison and AND/OR/NONE relation.
        """
        response = self._query(":MONI:VOLT:COND?")
        return (_fields(response)[0], _fields(response)[1])

    @monitor_voltage_condition.setter
    def monitor_voltage_condition(self, value: tuple[str, str]) -> None:
        """Set voltage comparison and AND/OR/NONE relation.

        Parameters
        ----------
        value : tuple[str, str]
            Voltage comparison and AND/OR/NONE relation.
        """
        self._write(":MONI:VOLT:COND " + f"{_token(value[0])},{_token(value[1])}")

    @property
    def monitor_current(self) -> float:
        """Monitor current threshold.

        Returns
        -------
        value : float
            Monitor current threshold.
        """
        response = self._query(":MONI:CURR?")
        return _number(response)

    @monitor_current.setter
    def monitor_current(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set monitor current threshold.

        Parameters
        ----------
        value : float or {"MIN", "MAX"}
            Monitor current threshold.
        """
        self._write(":MONI:CURR " + str(value))

    @property
    def monitor_current_condition(self) -> tuple[str, str]:
        """Current comparison and AND/OR/NONE relation.

        Returns
        -------
        value : tuple[str, str]
            Current comparison and AND/OR/NONE relation.
        """
        response = self._query(":MONI:CURR:COND?")
        return (_fields(response)[0], _fields(response)[1])

    @monitor_current_condition.setter
    def monitor_current_condition(self, value: tuple[str, str]) -> None:
        """Set current comparison and AND/OR/NONE relation.

        Parameters
        ----------
        value : tuple[str, str]
            Current comparison and AND/OR/NONE relation.
        """
        self._write(":MONI:CURR:COND " + f"{_token(value[0])},{_token(value[1])}")

    @property
    def monitor_power(self) -> float:
        """Monitor power threshold.

        Returns
        -------
        value : float
            Monitor power threshold.
        """
        response = self._query(":MONI:POWER?")
        return _number(response)

    @monitor_power.setter
    def monitor_power(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set monitor power threshold.

        Parameters
        ----------
        value : float or {"MIN", "MAX"}
            Monitor power threshold.
        """
        self._write(":MONI:POWER " + str(value))

    @property
    def monitor_power_condition(self) -> str:
        """Power comparison <P, >P or NONE.

        Returns
        -------
        value : str
            Power comparison <P, >P or NONE.
        """
        response = self._query(":MONI:POWER:COND?")
        return response.strip()

    @monitor_power_condition.setter
    def monitor_power_condition(self, value: str) -> None:
        """Set power comparison <P, >P or NONE.

        Parameters
        ----------
        value : str
            Power comparison <P, >P or NONE.
        """
        self._write(":MONI:POWER:COND " + _token(value))

    @property
    def monitor_enabled(self) -> bool:
        """Whether monitoring is enabled.

        Returns
        -------
        value : bool
            Whether monitoring is enabled.
        """
        response = self._query(":MONI?")
        return _enabled(response)

    @monitor_enabled.setter
    def monitor_enabled(self, value: bool) -> None:
        """Set whether monitoring is enabled.

        Parameters
        ----------
        value : bool
            Whether monitoring is enabled.
        """
        self._write(":MONI " + ("ON" if value else "OFF"))

    @property
    def monitor_stop_actions(self) -> tuple[bool, bool, bool]:
        """Output-off, warning and beeper action states.

        Returns
        -------
        value : tuple[bool, bool, bool]
            Output-off, warning and beeper action states.
        """
        response = self._query(":MONI:STOP?")
        output, warning, beeper = _fields(response)
        return _enabled(output), _enabled(warning), _enabled(beeper)

    def set_monitor_stop_action(self, action: str, enabled: bool) -> None:
        """Configure one monitor response.

        Parameters
        ----------
        action : str
            OUTOFF, WARN, BEEPER, or NONE (clear all).
        enabled : bool
            Enable the selected response.
        """
        self._write(f':MONI:STOP {_token(action)},{"ON" if enabled else "OFF"}')

    # --- OUTPut commands ---

    def get_output_mode(self, channel: int | None = None) -> str:
        """Get the output mode of the specified channel.

        The instrument offers two functionally equivalent commands to query the output
        mode: :OUTPut:CVCC? and :OUTPut:MODE?. There is no difference in the amount of
        data transferred. This method uses :OUTPut:MODE?.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        mode : str
            Output mode: 'CV', 'CC', or 'UR' representing constant voltage, constant
            current, or unregulated, respectively.
        """
        cmd = ":OUTP:MODE?"
        if channel is not None:
            cmd += f" CH{channel}"
        mode = self._query(cmd)

        return mode

    def get_ocp(self, channel: int | None = None) -> bool:
        """Query whether current of a channel has exceeded its OCP value.

        The output turns off automatically when the overcurrent protection (OCP) value
        is exceeded.

        The instrument offers two functionally equivalent commands to query whether the
        OCP value has been exceeded: :OUTPut:OCP:ALAR? and :OUTPut:OCP:QUES?. There is
        no difference in the amount of data transferred. This method uses
        :OUTPut:OCP:ALAR?.

        The instrument also provides a `source` command for this function, which is not
        used.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        ocp_alarm : bool
            If True, overcurrent protection value has been exceeded.
        """
        cmd = ":OUTP:OCP:ALAR?"
        if channel is not None:
            cmd += f" CH{channel}"
        response = self._query(cmd)
        return response == "YES"

    def clear_ocp_label(self, channel: int | None = None) -> None:
        """Clear the overcurrent protection alarm label.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = ":OUTP:OCP:CLEAR"
        if channel is not None:
            cmd += f" CH{channel}"
        self._write(cmd)

    def set_ocp_enable(self, enable: bool, channel: int | None = None) -> None:
        """Enable/disable the overcurrent protection function.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        enable : bool
            Enabled/disable overcurrent protection function.
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = ":OUTP:OCP "
        if channel is not None:
            cmd += f"CH{channel},"
        if enable is True:
            cmd += "ON"
        else:
            cmd += "OFF"
        self._write(cmd)

    def get_ocp_enable(self, channel: int | None = None) -> bool:
        """Query enable/disabled state of the overcurrent protection function.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        enable : bool
            Enabled/disabled state of overcurrent protection function.
        """
        cmd = ":OUTP:OCP?"
        if channel is not None:
            cmd += f" CH{channel}"
        response = self._query(cmd)
        return response == "ON"

    def set_ocp_value(
        self, value: float | Literal["MIN", "MAX"], channel: int | None = None
    ) -> None:
        """Set the overcurrent protection value for a channel.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        value : float; 'MIN', 'MAX'
            Overcurrent protection value.
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = ":OUTP:OCP:VAL "
        if channel is not None:
            cmd += f"CH{channel},"
        cmd += f"{value}"
        self._write(cmd)

    def get_ocp_value(
        self, channel: int | None = None, *, limit: Literal["MIN", "MAX"] | None = None
    ) -> float:
        """Get the overcurrent protection value for a channel.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        limit : {"MIN", "MAX"} or None, optional
            Query the supported bound instead of the configured value.

        Returns
        -------
        value : float
            Overcurrent protection value.
        """
        cmd = ":OUTP:OCP:VAL?"
        if channel is not None:
            cmd += f" CH{channel}"

        if limit is not None:
            cmd += ("," if channel is not None else " ") + _limit_args(limit).strip()
        value = _number(self._query(cmd))

        return value

    def get_ovp(self, channel: int | None = None) -> bool:
        """Query whether voltage of a channel has exceeded its OVP value.

        The output turns off automatically when the overvoltage protection (OVP) value
        is exceeded.

        The instrument offers two functionally equivalent commands to query whether the
        OVP value has been exceeded: :OUTPut:OVP:ALAR? and :OUTPut:OVP:QUES?. There is
        no difference in the amount of data transferred. This method uses
        :OUTPut:OVP:ALAR?.

        The instrument also provides a `source` command for this function, which is not
        used.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        ovp_alarm : bool
            If True, overvoltage protection value has been exceeded.
        """
        cmd = ":OUTP:OVP:ALAR?"
        if channel is not None:
            cmd += f" CH{channel}"
        response = self._query(cmd)
        return response == "YES"

    def clear_ovp_label(self, channel: int | None = None) -> None:
        """Clear the overvoltage protection alarm label.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = ":OUTP:OVP:CLEAR"
        if channel is not None:
            cmd += f" CH{channel}"
        self._write(cmd)

    def set_ovp_enable(self, enable: bool, channel: int | None = None) -> None:
        """Enable/disable the overvoltage protection function.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        enable : bool
            Enable/disable overvoltage protection function.
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = ":OUTP:OVP "
        if channel is not None:
            cmd += f"CH{channel},"
        if enable is True:
            cmd += "ON"
        else:
            cmd += "OFF"
        self._write(cmd)

    def get_ovp_enable(self, channel: int | None = None) -> bool:
        """Query enable/disabled state of the overvoltage protection function.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        enable : bool
            Enabled/disabled state of overvoltage protection function.
        """
        cmd = ":OUTP:OVP?"
        if channel is not None:
            cmd += f" CH{channel}"
        response = self._query(cmd)
        return response == "ON"

    def set_ovp_value(
        self, value: float | Literal["MIN", "MAX"], channel: int | None = None
    ) -> None:
        """Set the overvoltage protection value for a channel.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        value : float; 'MIN', 'MAX'
            Overvoltage protection value.
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = ":OUTP:OVP:VAL "
        if channel is not None:
            cmd += f"CH{channel},"
        cmd += f"{value}"
        self._write(cmd)

    def get_ovp_value(
        self, channel: int | None = None, *, limit: Literal["MIN", "MAX"] | None = None
    ) -> float:
        """Get the overvoltage protection value for a channel.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        limit : {"MIN", "MAX"} or None, optional
            Query the supported bound instead of the configured value.

        Returns
        -------
        value : float
            Overvoltage protection value.
        """
        cmd = ":OUTP:OVP:VAL?"
        if channel is not None:
            cmd += f" CH{channel}"

        if limit is not None:
            cmd += ("," if channel is not None else " ") + _limit_args(limit).strip()
        value = _number(self._query(cmd))

        return value

    def set_output_sense_enable(self, enable: bool, channel: int | None = None) -> None:
        """Enable/disable output sense function.

        Only supported on some channels for some models.

        Parameters
        ----------
        enable : bool
            Enable/disable the sense function.
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = ":OUTP:SENS "
        if channel is not None:
            cmd += f"CH{channel},"
        if enable is True:
            cmd += "ON"
        else:
            cmd += "OFF"
        self._write(cmd)

    def get_output_sense_enable(self, channel: int | None = None) -> bool:
        """Get enable/disable state of output sense function.

        Only supported on some channels for some models.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        enable : bool
            Enabled/disabled state of the sense function.
        """
        cmd = ":OUTP:SENS?"
        if channel is not None:
            cmd += f" CH{channel}"
        response = self._query(cmd)
        return response == "ON"

    def set_output_enable(self, enable: bool, channel: int | None = None) -> None:
        """Enable/disable the output of a channel.

        Parameters
        ----------
        enable : bool
            Enabled/disabled state of the channel output
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = ":OUTP "
        if channel is not None:
            cmd += f" CH{channel},"
        if enable is True:
            cmd += "ON"
        else:
            cmd += "OFF"
        self._write(cmd)

    def get_output_enable(self, channel: int | None = None) -> bool:
        """Get enabled/disabled state of the output of a channel.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        enable : bool
            Enabled/disabled state of the channel output.
        """
        cmd = ":OUTP?"
        if channel is not None:
            cmd += f" CH{channel}"
        response = self._query(cmd)
        return response == "ON"

    @property
    def output_range(self) -> str:
        """Single-channel voltage/current range; assign LOW or HIGH.

        Returns
        -------
        value : str
            Single-channel voltage/current range; assign LOW or HIGH.
        """
        response = self._query(":OUTP:RANG?")
        return response.strip()

    @output_range.setter
    def output_range(self, value: str) -> None:
        """Set single-channel voltage/current range; assign LOW or HIGH.

        Parameters
        ----------
        value : str
            Single-channel voltage/current range; assign LOW or HIGH.
        """
        self._write(":OUTP:RANG " + _token(value))

    def set_output_track(self, enabled: bool, channel: int | None = None) -> None:
        """Set tracking state on a supported channel.

        Parameters
        ----------
        enabled : bool
            Whether tracking is enabled.
        channel : int or None, optional
            Physical channel, or selected channel if omitted.
        """
        command = ":OUTP:TRAC"
        command += (f" CH{channel}," if channel is not None else " ") + (
            "ON" if enabled else "OFF"
        )
        self._write(command)

    def get_output_track(self, channel: int | None = None) -> bool:
        """Query tracking state; unsupported channels return False.

        Parameters
        ----------
        channel : int or None, optional
            Physical channel, or selected channel if omitted.

        Returns
        -------
        value : bool
            Query tracking state; unsupported channels return False.
        """
        command = ":OUTP:TRAC?"
        command += f" CH{channel}" if channel is not None else ""
        response = self._query(command).strip()
        return False if response == "NONE" else _enabled(response)

    # --- PRESet commands ---

    @property
    def preset_key(self) -> str:
        """Front-panel preset key selection DEFAULT or USER1–USER4.

        Returns
        -------
        value : str
            Front-panel preset key selection DEFAULT or USER1–USER4.
        """
        response = self._query(":PRES:KEY?")
        return response.strip()

    @preset_key.setter
    def preset_key(self, value: str) -> None:
        """Set front-panel preset key selection DEFAULT or USER1–USER4.

        Parameters
        ----------
        value : str
            Front-panel preset key selection DEFAULT or USER1–USER4.
        """
        self._write(":PRES:KEY " + _token(value))

    def apply_preset(self) -> None:
        """Apply the preset currently assigned to the preset key."""
        self._write(":PRES")

    def reset_preset(self, preset: int) -> None:
        """Reset preset editing values to defaults.

        Parameters
        ----------
        preset : int
            User preset index 1–4.
        """
        self._write(f":PRES:USER{preset}:SET:DEF")

    def save_preset(self, preset: int) -> None:
        """Commit edited values to a user preset.

        Parameters
        ----------
        preset : int
            User preset index 1–4.
        """
        self._write(f":PRES:USER{preset}:SET:SURE")

    def set_preset_voltage(
        self, preset: int, value: float | Literal["MIN", "MAX"]
    ) -> None:
        """Set a user preset voltage.

        Parameters
        ----------
        preset : int
            User preset index 1–4.
        value : float or {"MIN", "MAX"}
            Requested preset value.
        """
        command = f":PRES:USER{preset}:SET:VOLT"
        self._write(command + " " + str(value))

    def get_preset_voltage(
        self, preset: int, *, limit: Literal["MIN", "MAX"] | None = None
    ) -> float:
        """Query a user preset voltage.

        Parameters
        ----------
        preset : int
            User preset index 1–4.

        limit : {"MIN", "MAX"} or None, optional
            Query a threshold or level bound.

        Returns
        -------
        value : float
            Query a user preset voltage.
        """
        command = f":PRES:USER{preset}:SET:VOLT?"
        return _number(self._query(command + _limit_args(limit)))

    def set_preset_current(
        self, preset: int, value: float | Literal["MIN", "MAX"]
    ) -> None:
        """Set a user preset current.

        Parameters
        ----------
        preset : int
            User preset index 1–4.
        value : float or {"MIN", "MAX"}
            Requested preset value.
        """
        command = f":PRES:USER{preset}:SET:CURR"
        self._write(command + " " + str(value))

    def get_preset_current(
        self, preset: int, *, limit: Literal["MIN", "MAX"] | None = None
    ) -> float:
        """Query a user preset current.

        Parameters
        ----------
        preset : int
            User preset index 1–4.

        limit : {"MIN", "MAX"} or None, optional
            Query a threshold or level bound.

        Returns
        -------
        value : float
            Query a user preset current.
        """
        command = f":PRES:USER{preset}:SET:CURR?"
        return _number(self._query(command + _limit_args(limit)))

    def set_preset_otp_enabled(self, preset: int, value: bool) -> None:
        """Set a user preset otp enabled.

        Parameters
        ----------
        preset : int
            User preset index 1–4.
        value : bool
            Requested preset value.
        """
        command = f":PRES:USER{preset}:SET:OTP"
        self._write(command + " " + ("ON" if value else "OFF"))

    def get_preset_otp_enabled(self, preset: int) -> bool:
        """Query a user preset otp enabled.

        Parameters
        ----------
        preset : int
            User preset index 1–4.

        Returns
        -------
        value : bool
            Query a user preset otp enabled.
        """
        command = f":PRES:USER{preset}:SET:OTP?"
        return _enabled(self._query(command))

    def set_preset_tracking_enabled(self, preset: int, value: bool) -> None:
        """Set a user preset tracking enabled.

        Parameters
        ----------
        preset : int
            User preset index 1–4.
        value : bool
            Requested preset value.
        """
        command = f":PRES:USER{preset}:SET:TRAC"
        self._write(command + " " + ("ON" if value else "OFF"))

    def get_preset_tracking_enabled(self, preset: int) -> bool:
        """Query a user preset tracking enabled.

        Parameters
        ----------
        preset : int
            User preset index 1–4.

        Returns
        -------
        value : bool
            Query a user preset tracking enabled.
        """
        command = f":PRES:USER{preset}:SET:TRAC?"
        return _enabled(self._query(command))

    def set_preset_ocp(
        self,
        preset: int,
        enabled: bool,
        value: float | Literal["MIN", "MAX"] | None = None,
    ) -> None:
        """Set a user preset OCP enable state and optional threshold.

        Parameters
        ----------
        preset : int
            User preset index 1–4.
        enabled : bool
            Enable protection in this preset.
        value : float or {"MIN", "MAX"} or None, optional
            Threshold; omitted leaves its previous value.
        """
        command = f':PRES:USER{preset}:SET:OCP {"ON" if enabled else "OFF"}'
        if value is not None:
            command += f",{value}"
        self._write(command)

    def get_preset_ocp(
        self, preset: int, *, limit: Literal["MIN", "MAX"] | None = None
    ) -> tuple[bool, float]:
        """Read a user preset OCP state and threshold.

        Parameters
        ----------
        preset : int
            User preset index 1–4.

        limit : {"MIN", "MAX"} or None, optional
            Query a threshold or level bound.

        Returns
        -------
        value : tuple[bool, float]
            Read a user preset OCP state and threshold.
        """
        fields = _fields(
            self._query(f":PRES:USER{preset}:SET:OCP?" + _limit_args(limit))
        )
        return _enabled(fields[0]), _number(fields[1])

    def set_preset_ovp(
        self,
        preset: int,
        enabled: bool,
        value: float | Literal["MIN", "MAX"] | None = None,
    ) -> None:
        """Set a user preset OVP enable state and optional threshold.

        Parameters
        ----------
        preset : int
            User preset index 1–4.
        enabled : bool
            Enable protection in this preset.
        value : float or {"MIN", "MAX"} or None, optional
            Threshold; omitted leaves its previous value.
        """
        command = f':PRES:USER{preset}:SET:OVP {"ON" if enabled else "OFF"}'
        if value is not None:
            command += f",{value}"
        self._write(command)

    def get_preset_ovp(
        self, preset: int, *, limit: Literal["MIN", "MAX"] | None = None
    ) -> tuple[bool, float]:
        """Read a user preset OVP state and threshold.

        Parameters
        ----------
        preset : int
            User preset index 1–4.

        limit : {"MIN", "MAX"} or None, optional
            Query a threshold or level bound.

        Returns
        -------
        value : tuple[bool, float]
            Read a user preset OVP state and threshold.
        """
        fields = _fields(
            self._query(f":PRES:USER{preset}:SET:OVP?" + _limit_args(limit))
        )
        return _enabled(fields[0]), _number(fields[1])

    # --- RECorder commands ---

    @property
    def recorder_enabled(self) -> bool:
        """Whether recording is enabled.

        Returns
        -------
        value : bool
            Whether recording is enabled.
        """
        response = self._query(":REC?")
        return _enabled(response)

    @recorder_enabled.setter
    def recorder_enabled(self, value: bool) -> None:
        """Set whether recording is enabled.

        Parameters
        ----------
        value : bool
            Whether recording is enabled.
        """
        self._write(":REC " + ("ON" if value else "OFF"))

    @property
    def recorder_period(self) -> int:
        """Recording sample period in seconds.

        Returns
        -------
        value : int
            Recording sample period in seconds.
        """
        response = self._query(":REC:PERI?")
        return int(response)

    @recorder_period.setter
    def recorder_period(self, value: int) -> None:
        """Set recording sample period in seconds.

        Parameters
        ----------
        value : int
            Recording sample period in seconds.
        """
        self._write(":REC:PERI " + str(value))

    @property
    def recorder_destination(self) -> str:
        """Configured recording destination.

        Returns
        -------
        value : str
            Configured recording destination.
        """
        response = self._query(":REC:DEST?")
        return _fields(response)[0]

    def set_recorder_destination(
        self, location: int | str, filename: str | None = None
    ) -> None:
        """Configure an internal recording slot/name or external recording path.

        Parameters
        ----------
        location : int or str
            Internal slot 1–10 or external .ROF path.
        filename : str or None, optional
            Recording filename for an internal slot.
        """
        if isinstance(location, int):
            if filename is None:
                raise ValueError("Internal recording destinations require a filename.")
            self._write(f":REC:MEM {location}," + _quote(filename))
        else:
            if filename is not None:
                raise ValueError(
                    "External destinations specify their filename in the path."
                )
            self._write(":REC:MMEM " + _quote(location))

    # --- SOURce commands ---

    def set_current(
        self,
        current: float | Literal["MIN", "MAX", "UP", "DOWN"],
        channel: int | None = None,
    ) -> None:
        """Set the current of specified channel.

        Parameters
        ----------
        current : float; 'MAX', 'MIN'; 'UP', 'DOWN'
            Current level. 'UP' and 'DOWN' increment and decrement the current by step
            setting.
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = f":CURR {current}"
        if channel is not None:
            cmd = f":SOUR{channel}" + cmd
        self._write(cmd)

    def get_current(self, channel: int | None = None) -> float:
        """Get the current setting of a channel.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        current : float
            Current setting.
        """
        cmd = ":CURR?"
        if channel is not None:
            cmd = f":SOUR{channel}" + cmd
        current = float(self._query(cmd))

        return current

    def set_voltage(
        self,
        voltage: float | Literal["MIN", "MAX", "UP", "DOWN"],
        channel: int | None = None,
    ) -> None:
        """Set the voltage of specified channel.

        Parameters
        ----------
        voltage : float; 'MAX', 'MIN'; 'UP', 'DOWN'
            Voltage level. 'UP' and 'DOWN' increment and decrement the voltage by step
            setting.
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        cmd = f":VOLT {voltage}"
        if channel is not None:
            cmd = f":SOUR{channel}" + cmd
        self._write(cmd)

    def get_voltage(self, channel: int | None = None) -> float:
        """Get the voltage setting of a channel.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        voltage : float
            Voltage setting.
        """
        cmd = ":VOLT?"
        if channel is not None:
            cmd = f":SOUR{channel}" + cmd
        voltage = float(self._query(cmd))

        return voltage

    def set_current_step(
        self, value: float | Literal["DEF"], channel: int | None = None
    ) -> None:
        """Set current increment size.

        Parameters
        ----------
        value : float or {"DEF"}
            Step size or factory default.
        channel : int or None, optional
            Physical channel, or selected channel if omitted.
        """
        command = _source(":CURR:STEP", channel)
        self._write(f"{command} {value}")

    def get_current_step(
        self, channel: int | None = None, *, default: bool = False
    ) -> float:
        """Query current increment size.

        Parameters
        ----------
        channel : int or None, optional
            Physical channel, or selected channel if omitted.

        default : bool, optional
            Query the factory default step rather than the configured step.

        Returns
        -------
        value : float
            Query current increment size.
        """
        return _number(
            self._query(_source(":CURR:STEP?", channel) + (" DEF" if default else ""))
        )

    def set_voltage_step(
        self, value: float | Literal["DEF"], channel: int | None = None
    ) -> None:
        """Set voltage increment size.

        Parameters
        ----------
        value : float or {"DEF"}
            Step size or factory default.
        channel : int or None, optional
            Physical channel, or selected channel if omitted.
        """
        command = _source(":VOLT:STEP", channel)
        self._write(f"{command} {value}")

    def get_voltage_step(
        self, channel: int | None = None, *, default: bool = False
    ) -> float:
        """Query voltage increment size.

        Parameters
        ----------
        channel : int or None, optional
            Physical channel, or selected channel if omitted.

        default : bool, optional
            Query the factory default step rather than the configured step.

        Returns
        -------
        value : float
            Query voltage increment size.
        """
        return _number(
            self._query(_source(":VOLT:STEP?", channel) + (" DEF" if default else ""))
        )

    def clear_ocp_circuit(self, channel: int | None = None) -> None:
        """Clear OCP circuit and alarm, and re-enable the channel output.

        Parameters
        ----------
        channel : int or None, optional
            Physical channel, or selected channel if omitted.
        """
        self._write(_source(":CURR:PROT:CLE", channel))

    def clear_ovp_circuit(self, channel: int | None = None) -> None:
        """Clear OVP circuit and alarm, and re-enable the channel output.

        Parameters
        ----------
        channel : int or None, optional
            Physical channel, or selected channel if omitted.
        """
        self._write(_source(":VOLT:PROT:CLE", channel))

    def set_source_trigger(
        self,
        func: Literal["CURR", "VOLT"],
        level: float | Literal["MIN", "MAX"],
        channel: int | None = None,
    ) -> None:
        """Set a triggered current or voltage level.

        Parameters
        ----------
        func : {"CURR", "VOLT"}
            Triggered quantity.
        level : float or {"MIN", "MAX"}
            Triggered level.
        channel : int or None, optional
            Physical channel, or selected channel if omitted.
        """
        if func not in ("CURR", "VOLT"):
            raise ValueError("func must be CURR or VOLT.")
        command = _source(f":{func}:TRIG", channel)
        self._write(f"{command} {level}")

    def get_source_trigger(
        self,
        func: Literal["CURR", "VOLT"],
        channel: int | None = None,
        *,
        limit: Literal["MIN", "MAX"] | None = None,
    ) -> float:
        """Query a triggered current or voltage level.

        Parameters
        ----------
        func : {"CURR", "VOLT"}
            Triggered quantity.
        channel : int or None, optional
            Physical channel, or selected channel if omitted.
        limit : {"MIN", "MAX"} or None, optional
            Optional supported bound.

        Returns
        -------
        value : float
            Query a triggered current or voltage level.
        """
        if func not in ("CURR", "VOLT"):
            raise ValueError("func must be CURR or VOLT.")
        command = _source(f":{func}:TRIG", channel)
        return _number(self._query(command + "?" + _limit_args(limit)))

    # --- STATus commands ---

    @property
    def questionable_condition(self) -> int:
        """Questionable condition.

        Returns
        -------
        value : int
            questionable condition.
        """
        response = self._query(":STAT:QUES:COND?")
        return int(response)

    @property
    def questionable_enable_register(self) -> int:
        """Questionable enable register.

        Returns
        -------
        value : int
            questionable enable register.
        """
        response = self._query(":STAT:QUES:ENAB?")
        return int(response)

    @questionable_enable_register.setter
    def questionable_enable_register(self, value: int) -> None:
        """Set questionable enable register.

        Parameters
        ----------
        value : int
            questionable enable register.
        """
        self._write(":STAT:QUES:ENAB " + str(value))

    @property
    def instrument_questionable_enable_register(self) -> int:
        """Instrument questionable enable register.

        Returns
        -------
        value : int
            instrument questionable enable register.
        """
        response = self._query(":STAT:QUES:INST:ENAB?")
        return int(response)

    @instrument_questionable_enable_register.setter
    def instrument_questionable_enable_register(self, value: int) -> None:
        """Set instrument questionable enable register.

        Parameters
        ----------
        value : int
            instrument questionable enable register.
        """
        self._write(":STAT:QUES:INST:ENAB " + str(value))

    def get_questionable_event(self) -> int:
        """Read and consume the corresponding questionable event register.

        Returns
        -------
        value : int
            Read and consume the corresponding questionable event register.
        """
        return int(self._query(":STAT:QUES?"))

    def get_instrument_questionable_event(self) -> int:
        """Read and consume the corresponding questionable event register.

        Returns
        -------
        value : int
            Read and consume the corresponding questionable event register.
        """
        return int(self._query(":STAT:QUES:INST?"))

    def get_channel_questionable_condition(self, channel: int) -> int:
        """Read a physical channel questionable register.

        Parameters
        ----------
        channel : int
            One-based physical channel number.

        Returns
        -------
        value : int
            Read a physical channel questionable register.
        """
        return int(self._query(f":STAT:QUES:INST:ISUM{channel}:COND?"))

    def get_channel_questionable_enable(self, channel: int) -> int:
        """Read a physical channel questionable register.

        Parameters
        ----------
        channel : int
            One-based physical channel number.

        Returns
        -------
        value : int
            Read a physical channel questionable register.
        """
        return int(self._query(f":STAT:QUES:INST:ISUM{channel}:ENAB?"))

    def get_channel_questionable_event(self, channel: int) -> int:
        """Read and consume a physical channel questionable register.

        Parameters
        ----------
        channel : int
            One-based physical channel number.

        Returns
        -------
        value : int
            Read and consume a physical channel questionable register.
        """
        return int(self._query(f":STAT:QUES:INST:ISUM{channel}:EVEN?"))

    def set_channel_questionable_enable(self, value: int, channel: int) -> None:
        """Set a physical channel questionable enable mask.

        Parameters
        ----------
        value : int
            Register enable bitmask.
        channel : int
            One-based physical channel number.
        """
        self._write(f":STAT:QUES:INST:ISUM{channel}:ENAB {value}")

    # --- STORe commands ---

    def save_named_setup(self, slot: int, filename: str) -> None:
        """Save a named state file to an internal slot.

        Parameters
        ----------
        slot : int
            Internal state slot 1–10.
        filename : str
            State filename (.RSF).
        """
        self._write(f":STOR:LOC {slot}," + _quote(filename))

    # --- SYSTem commands ---

    @property
    def beeper_enabled(self) -> bool:
        """Beeper enabled.

        Returns
        -------
        value : bool
            beeper enabled.
        """
        response = self._query(":SYST:BEEP?")
        return _enabled(response)

    @beeper_enabled.setter
    def beeper_enabled(self, value: bool) -> None:
        """Set beeper enabled.

        Parameters
        ----------
        value : bool
            beeper enabled.
        """
        self._write(":SYST:BEEP " + ("ON" if value else "OFF"))

    @property
    def brightness(self) -> int:
        """Brightness.

        Returns
        -------
        value : int
            brightness.
        """
        response = self._query(":SYST:BRIG?")
        return int(response)

    @brightness.setter
    def brightness(self, value: int | Literal["MIN", "MAX"]) -> None:
        """Set brightness.

        Parameters
        ----------
        value : int or {"MIN", "MAX"}
            brightness.
        """
        self._write(":SYST:BRIG " + str(value))

    @property
    def contrast(self) -> int:
        """Contrast.

        Returns
        -------
        value : int
            contrast.
        """
        response = self._query(":SYST:CONT?")
        return int(response)

    @contrast.setter
    def contrast(self, value: int | Literal["MIN", "MAX"]) -> None:
        """Set contrast.

        Parameters
        ----------
        value : int or {"MIN", "MAX"}
            contrast.
        """
        self._write(":SYST:CONT " + str(value))

    @property
    def gpib_address(self) -> int:
        """Gpib address.

        Returns
        -------
        value : int
            gpib address.
        """
        response = self._query(":SYST:COMM:GPIB:ADDR?")
        return int(response)

    @gpib_address.setter
    def gpib_address(self, value: int) -> None:
        """Set gpib address.

        Parameters
        ----------
        value : int
            gpib address.
        """
        self._write(":SYST:COMM:GPIB:ADDR " + str(value))

    @property
    def lan_autoip_enabled(self) -> bool:
        """Lan autoip enabled.

        Returns
        -------
        value : bool
            lan autoip enabled.
        """
        response = self._query(":SYST:COMM:LAN:AUTO?")
        return _enabled(response)

    @lan_autoip_enabled.setter
    def lan_autoip_enabled(self, value: bool) -> None:
        """Set lan autoip enabled.

        Parameters
        ----------
        value : bool
            lan autoip enabled.
        """
        self._write(":SYST:COMM:LAN:AUTO " + ("ON" if value else "OFF"))

    @property
    def lan_dhcp_enabled(self) -> bool:
        """Lan dhcp enabled.

        Returns
        -------
        value : bool
            lan dhcp enabled.
        """
        response = self._query(":SYST:COMM:LAN:DHCP?")
        return _enabled(response)

    @lan_dhcp_enabled.setter
    def lan_dhcp_enabled(self, value: bool) -> None:
        """Set lan dhcp enabled.

        Parameters
        ----------
        value : bool
            lan dhcp enabled.
        """
        self._write(":SYST:COMM:LAN:DHCP " + ("ON" if value else "OFF"))

    @property
    def lan_dns(self) -> str:
        """Lan dns.

        Returns
        -------
        value : str
            lan dns.
        """
        response = self._query(":SYST:COMM:LAN:DNS?")
        return response.strip()

    @lan_dns.setter
    def lan_dns(self, value: str) -> None:
        """Set lan dns.

        Parameters
        ----------
        value : str
            lan dns.
        """
        self._write(":SYST:COMM:LAN:DNS " + _token(value))

    @property
    def lan_gateway(self) -> str:
        """Lan gateway.

        Returns
        -------
        value : str
            lan gateway.
        """
        response = self._query(":SYST:COMM:LAN:GATE?")
        return response.strip()

    @lan_gateway.setter
    def lan_gateway(self, value: str) -> None:
        """Set lan gateway.

        Parameters
        ----------
        value : str
            lan gateway.
        """
        self._write(":SYST:COMM:LAN:GATE " + _token(value))

    @property
    def lan_ip_address(self) -> str:
        """Lan ip address.

        Returns
        -------
        value : str
            lan ip address.
        """
        response = self._query(":SYST:COMM:LAN:IPAD?")
        return response.strip()

    @lan_ip_address.setter
    def lan_ip_address(self, value: str) -> None:
        """Set lan ip address.

        Parameters
        ----------
        value : str
            lan ip address.
        """
        self._write(":SYST:COMM:LAN:IPAD " + _token(value))

    @property
    def lan_mac_address(self) -> str:
        """Lan mac address.

        Returns
        -------
        value : str
            lan mac address.
        """
        response = self._query(":SYST:COMM:LAN:MAC?")
        return response.strip()

    @property
    def lan_manualip_enabled(self) -> bool:
        """Lan manualip enabled.

        Returns
        -------
        value : bool
            lan manualip enabled.
        """
        response = self._query(":SYST:COMM:LAN:MAN?")
        return _enabled(response)

    @lan_manualip_enabled.setter
    def lan_manualip_enabled(self, value: bool) -> None:
        """Set lan manualip enabled.

        Parameters
        ----------
        value : bool
            lan manualip enabled.
        """
        self._write(":SYST:COMM:LAN:MAN " + ("ON" if value else "OFF"))

    @property
    def lan_subnet_mask(self) -> str:
        """Lan subnet mask.

        Returns
        -------
        value : str
            lan subnet mask.
        """
        response = self._query(":SYST:COMM:LAN:SMASK?")
        return response.strip()

    @lan_subnet_mask.setter
    def lan_subnet_mask(self, value: str) -> None:
        """Set lan subnet mask.

        Parameters
        ----------
        value : str
            lan subnet mask.
        """
        self._write(":SYST:COMM:LAN:SMASK " + _token(value))

    @property
    def rs232_baud_rate(self) -> int:
        """Rs232 baud rate.

        Returns
        -------
        value : int
            rs232 baud rate.
        """
        response = self._query(":SYST:COMM:RS232:BAUD?")
        return int(response)

    @rs232_baud_rate.setter
    def rs232_baud_rate(self, value: int) -> None:
        """Set rs232 baud rate.

        Parameters
        ----------
        value : int
            rs232 baud rate.
        """
        self._write(":SYST:COMM:RS232:BAUD " + str(value))

    @property
    def rs232_data_bits(self) -> int:
        """Rs232 data bits.

        Returns
        -------
        value : int
            rs232 data bits.
        """
        response = self._query(":SYST:COMM:RS232:DATAB?")
        return int(response)

    @rs232_data_bits.setter
    def rs232_data_bits(self, value: int) -> None:
        """Set rs232 data bits.

        Parameters
        ----------
        value : int
            rs232 data bits.
        """
        self._write(":SYST:COMM:RS232:DATAB " + str(value))

    @property
    def rs232_flow_control_enabled(self) -> bool:
        """Rs232 flow control enabled.

        Returns
        -------
        value : bool
            rs232 flow control enabled.
        """
        response = self._query(":SYST:COMM:RS232:FLOWC?")
        return _enabled(response)

    @rs232_flow_control_enabled.setter
    def rs232_flow_control_enabled(self, value: bool) -> None:
        """Set rs232 flow control enabled.

        Parameters
        ----------
        value : bool
            rs232 flow control enabled.
        """
        self._write(":SYST:COMM:RS232:FLOWC " + ("ON" if value else "OFF"))

    @property
    def rs232_parity(self) -> str:
        """Rs232 parity.

        Returns
        -------
        value : str
            rs232 parity.
        """
        response = self._query(":SYST:COMM:RS232:PARI?")
        return response.strip()

    @rs232_parity.setter
    def rs232_parity(self, value: str) -> None:
        """Set rs232 parity.

        Parameters
        ----------
        value : str
            rs232 parity.
        """
        self._write(":SYST:COMM:RS232:PARI " + _token(value))

    @property
    def rs232_stop_bits(self) -> int:
        """Rs232 stop bits.

        Returns
        -------
        value : int
            rs232 stop bits.
        """
        response = self._query(":SYST:COMM:RS232:STOPB?")
        return int(response)

    @rs232_stop_bits.setter
    def rs232_stop_bits(self, value: int) -> None:
        """Set rs232 stop bits.

        Parameters
        ----------
        value : int
            rs232 stop bits.
        """
        self._write(":SYST:COMM:RS232:STOPB " + str(value))

    @property
    def language(self) -> str:
        """Language.

        Returns
        -------
        value : str
            language.
        """
        response = self._query(":SYST:LANG:TYPE?")
        return response.strip()

    @language.setter
    def language(self, value: str) -> None:
        """Set language.

        Parameters
        ----------
        value : str
            language.
        """
        self._write(":SYST:LANG:TYPE " + _token(value))

    @property
    def locked(self) -> bool:
        """Locked.

        Returns
        -------
        value : bool
            locked.
        """
        response = self._query(":SYST:LOCK?")
        return _enabled(response)

    @locked.setter
    def locked(self, value: bool) -> None:
        """Set locked.

        Parameters
        ----------
        value : bool
            locked.
        """
        self._write(":SYST:LOCK " + ("ON" if value else "OFF"))

    @property
    def on_off_sync_enabled(self) -> bool:
        """On off sync enabled.

        Returns
        -------
        value : bool
            on off sync enabled.
        """
        response = self._query(":SYST:ONOFFS?")
        return _enabled(response)

    @on_off_sync_enabled.setter
    def on_off_sync_enabled(self, value: bool) -> None:
        """Set on off sync enabled.

        Parameters
        ----------
        value : bool
            on off sync enabled.
        """
        self._write(":SYST:ONOFFS " + ("ON" if value else "OFF"))

    @property
    def otp_enabled(self) -> bool:
        """Otp enabled.

        Returns
        -------
        value : bool
            otp enabled.
        """
        response = self._query(":SYST:OTP?")
        return _enabled(response)

    @otp_enabled.setter
    def otp_enabled(self, value: bool) -> None:
        """Set otp enabled.

        Parameters
        ----------
        value : bool
            otp enabled.
        """
        self._write(":SYST:OTP " + ("ON" if value else "OFF"))

    @property
    def power_on_config_mode(self) -> str:
        """Power on config mode.

        Returns
        -------
        value : str
            power on config mode.
        """
        response = self._query(":SYST:POWE?")
        return response.strip()

    @power_on_config_mode.setter
    def power_on_config_mode(self, value: str) -> None:
        """Set power on config mode.

        Parameters
        ----------
        value : str
            power on config mode.
        """
        self._write(":SYST:POWE " + _token(value))

    @property
    def screen_saver_enabled(self) -> bool:
        """Screen saver enabled.

        Returns
        -------
        value : bool
            screen saver enabled.
        """
        response = self._query(":SYST:SAV?")
        return _enabled(response)

    @screen_saver_enabled.setter
    def screen_saver_enabled(self, value: bool) -> None:
        """Set screen saver enabled.

        Parameters
        ----------
        value : bool
            screen saver enabled.
        """
        self._write(":SYST:SAV " + ("ON" if value else "OFF"))

    @property
    def track_mode(self) -> str:
        """Track mode.

        Returns
        -------
        value : str
            track mode.
        """
        response = self._query(":SYST:TRACKM?")
        return response.strip()

    @track_mode.setter
    def track_mode(self, value: str) -> None:
        """Set track mode.

        Parameters
        ----------
        value : str
            track mode.
        """
        self._write(":SYST:TRACKM " + _token(value))

    @property
    def scpi_version(self) -> str:
        """Scpi version.

        Returns
        -------
        value : str
            scpi version.
        """
        response = self._query(":SYST:VERS?")
        return response.strip()

    def get_errors(self) -> list[str]:
        """Read and remove queued errors until the instrument reports no error.

        Error responses are returned unchanged, excluding the final zero-code
        response. Each response is preserved whole, including any batched error
        entries. The query wrapper disables error checks to prevent recursion.
        The configured VISA timeout and query delay are used without overrides.

        Returns
        -------
        errors : list of str
            Raw nonzero error responses, or an empty list when no errors exist.
        """
        errors: list[str] = []
        while True:
            response = self._query(":SYST:ERR?", check_errors=False)
            code, separator, message = response.partition(",")
            if (
                not separator
                or not message.strip().startswith('"')
                or not message.strip().endswith('"')
            ):
                raise ValueError(response)
            if int(code) == 0:
                return errors
            errors.append(response)

    @property
    def keylock_enabled(self) -> bool:
        """Query enable/disable state of front panel keys in remote mode.

        Each read or assignment performs VISA I/O and can raise communication
        errors.

        Returns
        -------
        enable : bool
            Enabled/disabled state of the front panel lock
        """
        cmd = ":SYST:KLOC:STAT?"
        response = self._query(":SYST:KLOC:STAT?")
        return response == "ON"

    @keylock_enabled.setter
    def keylock_enabled(self, enable: bool) -> None:
        """Enable/disable front panel keys in remote mode.

        Parameters
        ----------
        enable : bool
            Enabled/disabled state of the front panel lock
        """
        cmd = ":SYST:KLOC:STAT "
        if enable is True:
            cmd += "ON"
        else:
            cmd += "OFF"
        self._write(cmd)

    def set_local(self) -> None:
        """Return instrument to local mode."""
        self._write(":SYST:LOC")

    def set_remote(self) -> None:
        """Switch to remote mode and restrict front-panel operations.

        Call after connect() when desired. This explicit mode change checks
        the instrument error queue like other commands.
        """
        self._write(":SYST:REM")

    @property
    def temperature_test_result(self) -> float:
        """Query the self-test result of the temperature.

        Each access performs VISA I/O and can raise communication errors.

        Returns
        -------
        temperature : float
            Temperature in degrees Celsius.
        """
        temperature = float(self._query(":SYST:SELF:TEST:TEMP?"))

        return temperature

    def beep(self) -> None:
        """Sound the beeper once."""
        self._write(":SYST:BEEP:IMM")

    def apply_lan_config(self) -> None:
        """Apply pending LAN settings; the current connection may be lost."""
        self._write(":SYST:COMM:LAN:APPL")

    def set_key_lock(self, key: str, enabled: bool) -> None:
        """Lock or unlock an individual front-panel key.

        Parameters
        ----------
        key : str
            Guide key token, such as CH1, NUM0, OUTPUT1 or ALL.
        enabled : bool
            Whether to lock this key.
        """
        self._write(f':SYST:KLOC {_token(key)},{"ON" if enabled else "OFF"}')

    def get_key_lock(self, key: str) -> bool:
        """Query an individual front-panel key lock.

        Parameters
        ----------
        key : str
            Guide key token or ALL.

        Returns
        -------
        value : bool
            Query an individual front-panel key lock.
        """
        return _enabled(self._query(f":SYST:KLOC? {_token(key)}"))

    def get_board_test_results(
        self, board: Literal["TOP", "BOTTOM"] | None = None
    ) -> list[str]:
        """Read one or both board self-test results.

        Parameters
        ----------
        board : {"TOP", "BOTTOM"} or None, optional
            Board to inspect; omitted returns both.

        Returns
        -------
        value : list[str]
            Read one or both board self-test results.
        """
        command = ":SYST:SELF:TEST:BOARD?" + (f" {board}" if board is not None else "")
        return _fields(self._query(command))

    @property
    def fan_test_result(self) -> str:
        """Fan self-test result.

        Returns
        -------
        value : str
            Fan self-test result.
        """
        response = self._query(":SYST:SELF:TEST:FAN?")
        return response.strip()

    # --- TIMEr commands ---

    @property
    def timer_cycles(self) -> tuple[str, int | None]:
        """Timer cycles.

        Returns
        -------
        value : tuple[str, int | None]
            timer cycles.
        """
        response = self._query(":TIME:CYCLE?")
        return (
            _fields(response)[0],
            int(_fields(response)[1]) if len(_fields(response)) > 1 else None,
        )

    @timer_cycles.setter
    def timer_cycles(self, value: tuple[str, int | None]) -> None:
        """Set timer cycles.

        Parameters
        ----------
        value : tuple[str, int | None]
            timer cycles.
        """
        self._write(
            ":TIME:CYCLE "
            + _token(value[0])
            + (f",{value[1]}" if value[1] is not None else "")
        )

    @property
    def timer_end_state(self) -> str:
        """Timer end state.

        Returns
        -------
        value : str
            timer end state.
        """
        response = self._query(":TIME:ENDS?")
        return response.strip()

    @timer_end_state.setter
    def timer_end_state(self, value: str) -> None:
        """Set timer end state.

        Parameters
        ----------
        value : str
            timer end state.
        """
        self._write(":TIME:ENDS " + _token(value))

    @property
    def timer_groups(self) -> int:
        """Timer groups.

        Returns
        -------
        value : int
            timer groups.
        """
        response = self._query(":TIME:GROUP?")
        return int(response)

    @timer_groups.setter
    def timer_groups(self, value: int) -> None:
        """Set timer groups.

        Parameters
        ----------
        value : int
            timer groups.
        """
        self._write(":TIME:GROUP " + str(value))

    @property
    def timer_enabled(self) -> bool:
        """Timer enabled.

        Returns
        -------
        value : bool
            timer enabled.
        """
        response = self._query(":TIME?")
        return _enabled(response)

    @timer_enabled.setter
    def timer_enabled(self, value: bool) -> None:
        """Set timer enabled.

        Parameters
        ----------
        value : bool
            timer enabled.
        """
        self._write(":TIME " + ("ON" if value else "OFF"))

    @property
    def timer_template(self) -> str:
        """Timer template.

        Returns
        -------
        value : str
            timer template.
        """
        response = self._query(":TIME:TEMP:SEL?")
        return response.strip()

    @timer_template.setter
    def timer_template(self, value: str) -> None:
        """Set timer template.

        Parameters
        ----------
        value : str
            timer template.
        """
        self._write(":TIME:TEMP:SEL " + _token(value))

    @property
    def timer_template_object(self) -> tuple[str, float]:
        """Timer template object.

        Returns
        -------
        value : tuple[str, float]
            timer template object.
        """
        response = self._query(":TIME:TEMP:OBJ?")
        return (_fields(response)[0], _number(_fields(response)[1]))

    @timer_template_object.setter
    def timer_template_object(self, value: tuple[str, float]) -> None:
        """Set timer template object.

        Parameters
        ----------
        value : tuple[str, float]
            timer template object.
        """
        self._write(":TIME:TEMP:OBJ " + f"{_token(value[0])},{value[1]}")

    @property
    def timer_template_max(self) -> float:
        """Timer template max.

        Returns
        -------
        value : float
            timer template max.
        """
        response = self._query(":TIME:TEMP:MAXV?")
        return _number(response)

    @timer_template_max.setter
    def timer_template_max(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set timer template max.

        Parameters
        ----------
        value : float or {"MIN", "MAX"}
            timer template max.
        """
        self._write(":TIME:TEMP:MAXV " + str(value))

    @property
    def timer_template_min(self) -> float:
        """Timer template min.

        Returns
        -------
        value : float
            timer template min.
        """
        response = self._query(":TIME:TEMP:MINV?")
        return _number(response)

    @timer_template_min.setter
    def timer_template_min(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set timer template min.

        Parameters
        ----------
        value : float or {"MIN", "MAX"}
            timer template min.
        """
        self._write(":TIME:TEMP:MINV " + str(value))

    @property
    def timer_template_inverted(self) -> bool:
        """Timer template inverted.

        Returns
        -------
        value : bool
            timer template inverted.
        """
        response = self._query(":TIME:TEMP:INVE?")
        return _enabled(response)

    @timer_template_inverted.setter
    def timer_template_inverted(self, value: bool) -> None:
        """Set timer template inverted.

        Parameters
        ----------
        value : bool
            timer template inverted.
        """
        self._write(":TIME:TEMP:INVE " + ("ON" if value else "OFF"))

    @property
    def timer_template_fall_rate(self) -> int:
        """fall rate of the timer waveform template.

        Returns
        -------
        value : int
            fall rate of the timer waveform template.
        """
        response = self._query(":TIME:TEMP:FALLR?")
        return int(response)

    @timer_template_fall_rate.setter
    def timer_template_fall_rate(self, value: int) -> None:
        """Set fall rate of the timer waveform template.

        Parameters
        ----------
        value : int
            fall rate of the timer waveform template.
        """
        self._write(":TIME:TEMP:FALLR " + str(value))

    @property
    def timer_template_rise_rate(self) -> int:
        """rise rate of the timer waveform template.

        Returns
        -------
        value : int
            rise rate of the timer waveform template.
        """
        response = self._query(":TIME:TEMP:RISER?")
        return int(response)

    @timer_template_rise_rate.setter
    def timer_template_rise_rate(self, value: int) -> None:
        """Set rise rate of the timer waveform template.

        Parameters
        ----------
        value : int
            rise rate of the timer waveform template.
        """
        self._write(":TIME:TEMP:RISER " + str(value))

    @property
    def timer_template_interval(self) -> int:
        """interval of the timer waveform template.

        Returns
        -------
        value : int
            interval of the timer waveform template.
        """
        response = self._query(":TIME:TEMP:INTE?")
        return int(response)

    @timer_template_interval.setter
    def timer_template_interval(self, value: int) -> None:
        """Set interval of the timer waveform template.

        Parameters
        ----------
        value : int
            interval of the timer waveform template.
        """
        self._write(":TIME:TEMP:INTE " + str(value))

    @property
    def timer_template_period(self) -> int:
        """period of the timer waveform template.

        Returns
        -------
        value : int
            period of the timer waveform template.
        """
        response = self._query(":TIME:TEMP:PERI?")
        return int(response)

    @timer_template_period.setter
    def timer_template_period(self, value: int) -> None:
        """Set period of the timer waveform template.

        Parameters
        ----------
        value : int
            period of the timer waveform template.
        """
        self._write(":TIME:TEMP:PERI " + str(value))

    @property
    def timer_template_points(self) -> int:
        """points of the timer waveform template.

        Returns
        -------
        value : int
            points of the timer waveform template.
        """
        response = self._query(":TIME:TEMP:POINT?")
        return int(response)

    @timer_template_points.setter
    def timer_template_points(self, value: int) -> None:
        """Set points of the timer waveform template.

        Parameters
        ----------
        value : int
            points of the timer waveform template.
        """
        self._write(":TIME:TEMP:POINT " + str(value))

    @property
    def timer_template_symmetry(self) -> int:
        """symmetry of the timer waveform template.

        Returns
        -------
        value : int
            symmetry of the timer waveform template.
        """
        response = self._query(":TIME:TEMP:SYMM?")
        return int(response)

    @timer_template_symmetry.setter
    def timer_template_symmetry(self, value: int) -> None:
        """Set symmetry of the timer waveform template.

        Parameters
        ----------
        value : int
            symmetry of the timer waveform template.
        """
        self._write(":TIME:TEMP:SYMM " + str(value))

    @property
    def timer_template_width(self) -> int:
        """width of the timer waveform template.

        Returns
        -------
        value : int
            width of the timer waveform template.
        """
        response = self._query(":TIME:TEMP:WIDT?")
        return int(response)

    @timer_template_width.setter
    def timer_template_width(self, value: int) -> None:
        """Set width of the timer waveform template.

        Parameters
        ----------
        value : int
            width of the timer waveform template.
        """
        self._write(":TIME:TEMP:WIDT " + str(value))

    def construct_timer_template(self) -> None:
        """Generate timer entries from the selected template and parameters."""
        self._write(":TIME:TEMP:CONST")

    def set_timer_parameters(
        self, index: int, voltage: float, current: float, duration: float
    ) -> None:
        """Set one timer entry for the selected channel.

        Parameters
        ----------
        index : int
            Zero-based entry number, 0–2047.
        voltage : float
            Voltage in volts.
        current : float
            Current in amps.
        duration : float
            Duration in seconds, 1–99999.
        """
        self._write(f":TIME:PARA {index},{voltage},{current},{duration}")

    def get_timer_parameters(
        self, first: int = 0, count: int = 1
    ) -> list[tuple[int, float, float, float]]:
        """Read timer entries for the selected channel.

        Parameters
        ----------
        first : int, optional
            First zero-based entry, default 0.
        count : int, optional
            Number of entries, default 1.

        Returns
        -------
        value : list[tuple[int, float, float, float]]
            Read timer entries for the selected channel.
        """
        rows = _block(self._query(f":TIME:PARA? {first},{count}"))
        return [
            (int(fields[0]), _number(fields[1]), _number(fields[2]), _number(fields[3]))
            for row in rows.split(";")
            if row.strip()
            for fields in [_fields(row)]
        ]

    # --- TRIGger commands ---

    @property
    def trigger_source(self) -> str:
        """Trigger source BUS or IMM.

        Returns
        -------
        value : str
            Trigger source BUS or IMM.
        """
        response = self._query(":TRIG:SOUR?")
        return response.strip()

    @trigger_source.setter
    def trigger_source(self, value: str) -> None:
        """Set trigger source BUS or IMM.

        Parameters
        ----------
        value : str
            Trigger source BUS or IMM.
        """
        self._write(":TRIG:SOUR " + _token(value))

    @property
    def trigger_delay(self) -> float:
        """Trigger delay in seconds, 0–3600.

        Returns
        -------
        value : float
            Trigger delay in seconds, 0–3600.
        """
        response = self._query(":TRIG:DEL?")
        return _number(response)

    @trigger_delay.setter
    def trigger_delay(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set trigger delay in seconds, 0–3600.

        Parameters
        ----------
        value : float or {"MIN", "MAX"}
            Trigger delay in seconds, 0–3600.
        """
        self._write(":TRIG:DEL " + str(value))

    def set_trigger_input_enabled(self, value: bool, line: int | None = None) -> None:
        """Set digital trigger input enabled.

        Parameters
        ----------
        value : bool
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = "ON" if value else "OFF"
        self._write(":TRIG:IN " + (address + "," if address else "") + payload)

    def get_trigger_input_enabled(self, line: int | None = None) -> bool:
        """Read digital trigger input enabled.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : bool
            Read digital trigger input enabled.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:IN?" + (" " + address if address else ""))
        return _enabled(_fields(response)[-1])

    def set_trigger_input_source(
        self, value: list[str], line: int | None = None
    ) -> None:
        """Set digital trigger input source.

        Parameters
        ----------
        value : list[str]
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = ",".join(_token(item) for item in value)
        self._write(":TRIG:IN:SOUR " + (address + "," if address else "") + payload)

    def get_trigger_input_source(self, line: int | None = None) -> list[str]:
        """Read digital trigger input source.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : list[str]
            Read digital trigger input source.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:IN:SOUR?" + (" " + address if address else ""))
        return _fields(response) if response.strip() not in ("", "NONE") else []

    def set_trigger_input_response(self, value: str, line: int | None = None) -> None:
        """Set digital trigger input response.

        Parameters
        ----------
        value : str
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = _token(value)
        self._write(":TRIG:IN:RESP " + (address + "," if address else "") + payload)

    def get_trigger_input_response(self, line: int | None = None) -> str:
        """Read digital trigger input response.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : str
            Read digital trigger input response.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:IN:RESP?" + (" " + address if address else ""))
        return response.strip()

    def set_trigger_input_sensitivity(
        self, value: str, line: int | None = None
    ) -> None:
        """Set digital trigger input sensitivity.

        Parameters
        ----------
        value : str
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = _token(value)
        self._write(":TRIG:IN:SENS " + (address + "," if address else "") + payload)

    def get_trigger_input_sensitivity(self, line: int | None = None) -> str:
        """Read digital trigger input sensitivity.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : str
            Read digital trigger input sensitivity.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:IN:SENS?" + (" " + address if address else ""))
        return response.strip()

    def set_trigger_input_type(self, value: str, line: int | None = None) -> None:
        """Set digital trigger input type.

        Parameters
        ----------
        value : str
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = _token(value)
        self._write(":TRIG:IN:TYPE " + (address + "," if address else "") + payload)

    def get_trigger_input_type(self, line: int | None = None) -> str:
        """Read digital trigger input type.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : str
            Read digital trigger input type.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:IN:TYPE?" + (" " + address if address else ""))
        return response.strip()

    def set_trigger_output_enabled(self, value: bool, line: int | None = None) -> None:
        """Set digital trigger output enabled.

        Parameters
        ----------
        value : bool
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = "ON" if value else "OFF"
        self._write(":TRIG:OUT " + (address + "," if address else "") + payload)

    def get_trigger_output_enabled(self, line: int | None = None) -> bool:
        """Read digital trigger output enabled.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : bool
            Read digital trigger output enabled.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:OUT?" + (" " + address if address else ""))
        return _enabled(_fields(response)[-1])

    def set_trigger_output_source(self, value: str, line: int | None = None) -> None:
        """Set digital trigger output source.

        Parameters
        ----------
        value : str
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = _token(value)
        self._write(":TRIG:OUT:SOUR " + (address + "," if address else "") + payload)

    def get_trigger_output_source(self, line: int | None = None) -> str:
        """Read digital trigger output source.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : str
            Read digital trigger output source.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:OUT:SOUR?" + (" " + address if address else ""))
        return response.strip()

    def set_trigger_output_duty_cycle(
        self, value: int, line: int | None = None
    ) -> None:
        """Set digital trigger output duty cycle.

        Parameters
        ----------
        value : int
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = str(value)
        self._write(":TRIG:OUT:DUTY " + (address + "," if address else "") + payload)

    def get_trigger_output_duty_cycle(self, line: int | None = None) -> int:
        """Read digital trigger output duty cycle.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : int
            Read digital trigger output duty cycle.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:OUT:DUTY?" + (" " + address if address else ""))
        return int(response)

    def set_trigger_output_period(self, value: float, line: int | None = None) -> None:
        """Set digital trigger output period.

        Parameters
        ----------
        value : float
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = str(value)
        self._write(":TRIG:OUT:PERI " + (address + "," if address else "") + payload)

    def get_trigger_output_period(self, line: int | None = None) -> float:
        """Read digital trigger output period.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : float
            Read digital trigger output period.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:OUT:PERI?" + (" " + address if address else ""))
        return _number(response)

    def set_trigger_output_polarity(self, value: str, line: int | None = None) -> None:
        """Set digital trigger output polarity.

        Parameters
        ----------
        value : str
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = _token(value)
        self._write(":TRIG:OUT:POLA " + (address + "," if address else "") + payload)

    def get_trigger_output_polarity(self, line: int | None = None) -> str:
        """Read digital trigger output polarity.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : str
            Read digital trigger output polarity.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:OUT:POLA?" + (" " + address if address else ""))
        return response.strip()

    def set_trigger_output_signal(self, value: str, line: int | None = None) -> None:
        """Set digital trigger output signal.

        Parameters
        ----------
        value : str
            Requested digital trigger setting.
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.
        """
        address = f"D{line}" if line is not None else ""
        payload = _token(value)
        self._write(":TRIG:OUT:SIGN " + (address + "," if address else "") + payload)

    def get_trigger_output_signal(self, line: int | None = None) -> str:
        """Read digital trigger output signal.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3; omitted uses the selected line.

        Returns
        -------
        value : str
            Read digital trigger output signal.
        """
        address = f"D{line}" if line is not None else ""
        response = self._query(":TRIG:OUT:SIGN?" + (" " + address if address else ""))
        return response.strip()

    def set_trigger_output_condition(
        self,
        condition: str,
        value: float | Literal["MIN", "MAX"] | None = None,
        line: int | None = None,
    ) -> None:
        """Set a digital output trigger condition and optional threshold.

        Parameters
        ----------
        condition : str
            OUTOFF, OUTON, AUTO, or a <, >, = comparison with V, C or P.
        value : float or {"MIN", "MAX"} or None, optional
            Threshold for comparison conditions.
        line : int or None, optional
            Digital line 0–3, or selected line.
        """
        payload = _token(condition) + (f",{value}" if value is not None else "")
        self._write(
            ":TRIG:OUT:COND " + (f"D{line}," if line is not None else "") + payload
        )

    def get_trigger_output_condition(
        self, line: int | None = None, *, limit: Literal["MIN", "MAX"] | None = None
    ) -> tuple[str, float | None]:
        """Read a digital output trigger condition and optional threshold.

        Parameters
        ----------
        line : int or None, optional
            Digital line 0–3, or selected line.
        limit : {"MIN", "MAX"} or None, optional
            Query the threshold bound.

        Returns
        -------
        value : tuple[str, float | None]
            Read a digital output trigger condition and optional threshold.
        """
        address = f" D{line}" if line is not None else ""
        if limit is not None:
            address += ("," if line is not None else " ,") + _limit_args(limit).strip()
        fields = _fields(self._query(":TRIG:OUT:COND?" + address))
        return fields[0], _number(fields[1]) if len(fields) > 1 else None

    # --- Limits commands ---

    def get_limit(self, setting: str, limit: Literal["MIN", "MAX"]) -> float:
        """Read a documented bound of a scalar setting on the selected channel.

        Parameters
        ----------
        setting : str
            Property name documented in the API reference limit table.
        limit : {"MIN", "MAX"}
            Lower or upper bound to query.

        Returns
        -------
        value : float
            Read a documented bound of a scalar setting on the selected channel.
        """
        commands = {
            "analyzer_start_time": ":ANAL:STARTT",
            "analyzer_end_time": ":ANAL:ENDT",
            "delay_stop_condition": ":DELAY:STOP",
            "monitor_voltage": ":MONI:VOLT",
            "monitor_current": ":MONI:CURR",
            "monitor_power": ":MONI:POWER",
            "brightness": ":SYST:BRIG",
            "contrast": ":SYST:CONT",
            "timer_template_object": ":TIME:TEMP:OBJ",
            "timer_template_max": ":TIME:TEMP:MAXV",
            "timer_template_min": ":TIME:TEMP:MINV",
            "trigger_delay": ":TRIG:DEL",
        }
        if setting not in commands:
            raise ValueError("This setting has no MIN/MAX query selector.")
        response = self._query(commands[setting] + "?" + _limit_args(limit))
        return _number(_fields(response)[-1])


__all__ = [
    "DP800",
    "InstrumentError",
    "ENCODING",
    "WRITE_TERMINATION",
    "READ_TERMINATION",
    "PROTOCOL_RESOURCE_SETTINGS",
    "NOT_CONNECTED_MESSAGE",
    "SERIAL_TERMINATION",
    "SERIAL_PROTOCOL_RESOURCE_SETTINGS",
]
