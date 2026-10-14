# SPDX-License-Identifier: GPL-3.0-or-later

"""Rigol DP800 series power supply control library.

The full instrument manual, including the programming guide, can be found at
https://www.rigolna.com/products/dc-power-loads/dp800/.
"""

import logging
import warnings
from collections.abc import Mapping
from types import MappingProxyType, TracebackType
from typing import Any, Final, Literal

import pyvisa
from pyvisa.resources import MessageBasedResource, Resource

from .channel import DP800Channel

# Fixed SCPI framing used by the driver, shared by all connections.
ENCODING: Final = "ascii"
WRITE_TERMINATION: Final = "\n"
READ_TERMINATION: Final = "\n"
PROTOCOL_RESOURCE_SETTINGS: Final = MappingProxyType(
    {
        "encoding": ENCODING,
        "write_termination": WRITE_TERMINATION,
        "read_termination": READ_TERMINATION,
    }
)

NOT_CONNECTED_MESSAGE: Final = "Instrument is not connected."

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class InstrumentError(RuntimeError):
    """Raw error-queue responses reported by the instrument."""


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

        Stale errors are read and cleared before _instr is assigned. Call
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
            ASCII encoding and LF ("\\n") read/write termination. Conflicting
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
        for key, required in PROTOCOL_RESOURCE_SETTINGS.items():
            if key in resource_kwargs and resource_kwargs[key] != required:
                warnings.warn(
                    f"The driver owns {key}; the supplied value "
                    f"{resource_kwargs[key]!r} will be ignored. Using {required!r}.",
                    stacklevel=2,
                )
        resource_kwargs.update(PROTOCOL_RESOURCE_SETTINGS)
        manager = (
            pyvisa.ResourceManager() if resource_manager is None else resource_manager
        )
        resource: Resource | None = None
        try:
            resource = manager.open_resource(resource_name, **resource_kwargs)
            if not isinstance(resource, MessageBasedResource):
                raise TypeError("DP800 requires a message-based VISA resource.")
            self.get_errors(_resource=resource)
        except BaseException:
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    logger.warning(
                        "Failed to close instrument during initialization cleanup.",
                        exc_info=True,
                    )
            raise
        self._instr = resource

    def disconnect(self) -> None:
        """Disable outputs, return to local mode, and release the connection.

        Already disconnected instances are a no-op. All three output-disable
        commands and local mode are attempted even if one fails. The resource
        is then closed, and _instr is cleared even if cleanup fails. The driver
        does not explicitly close the manager. The first error is
        re-raised after cleanup; subsequent errors are logged.
        """
        resource = self._instr
        if resource is None:
            return
        error: Exception | None = None
        try:
            for command in (
                ":OUTP  CH1,OFF",
                ":OUTP  CH2,OFF",
                ":OUTP  CH3,OFF",
                ":SYST:LOC",
            ):
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

    def _query(self, command: str) -> str:
        """Read a query response, then check the instrument error queue.

        A VISA timeout triggers best-effort error diagnostics using the configured
        PyVISA timeout. Instrument errors are chained from the original timeout.
        Empty, malformed, or failed diagnostics preserve the original exception.
        This recovery attempt does not guarantee response synchronization.

        Parameters
        ----------
        command : str
            SCPI command to send to the instrument.

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
            if original.error_code != pyvisa.constants.StatusCode.error_timeout:
                raise
            try:
                errors = self.get_errors()
            except Exception:
                errors = []
            if errors:
                raise InstrumentError("\n".join(errors)) from original
            raise
        self._check_errors()
        return response

    def _check_errors(self) -> None:
        """Raise the raw instrument error responses if the queue is nonempty."""
        errors = self.get_errors()
        if errors:
            raise InstrumentError("\n".join(errors))

    # --- ANALyser commands ---

    # --- APPLy commands---

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

        cmd = ":APPL "

        # TODO: test what happens if channel is None on multi-channel instrument
        if channel is not None:
            cmd += f"CH{channel},"

        # this function can be used to set voltage only
        if voltage is not None:
            cmd += f"{voltage}"

        # this function can't be used to set current only
        if {voltage is not None} & {current is not None}:
            cmd += f",{current}"

        self._write(cmd)

    def get_apply(
        self,
        channel: int | None = None,
        function: Literal["CURR", "VOLT"] | None = None,
    ) -> float | str | tuple[str, str, float, float]:
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
        resp : float or list
            If both `channel` and `function` are specified, the set value of the
            desired function is returned. If `function` is omitted, a list is returned
            comprised of the currently selected channel, its rated values, the set
            value of the voltage, and the set value of the current.
        """
        cmd = ":APPL?"

        if channel is not None:
            cmd += f" CH{channel}"

        # channel cannot be omitted on its own. If channel is omitted, function also
        # has to be omitted.
        if (channel is not None) & (function is not None):
            cmd += f",{function}"
            resp = float(self._query(cmd))

            return resp
        elif (channel is None) & (function is not None):
            warnings.warn(
                "When querying using APPL? you may omit both `channel` and `function` parameters or `function` only. You cannot only omit `channel`."
            )
            cmd += f",{function}"
            return self._query(cmd)
        else:
            ch, rating, voltage, current = self._query(cmd).split(",")

            return ch, rating, float(voltage), float(current)

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
            paramter is ignored. Must be in range 1 - 99999.
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

    def set_delay_parameters(self) -> None:
        """Set the delayer parameters of the specified group.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_delay_parameters(self) -> None:
        """Get the delayer parameters of the specified group.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_delay_state(self, enable: bool) -> None:
        """Enable/disable the delay output function.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.

        Applies to currently selected channel.

        Parameters
        ----------

        Parameters
        ----------
        enable : bool
            Whether the setting should be enabled.
        """
        warnings.warn("Not implemented.")

    def get_delay_state(self, enable: bool) -> None:
        """Get the enable/disable state of the delay output function.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.

        Applies to current channel.

        Parameters
        ----------
        enable : bool
            Whether the setting should be enabled.
        """
        warnings.warn("Not implemented.")

    def set_delay_state_pattern(self) -> None:
        """Set the delay state pattern.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_delay_state_pattern(self) -> None:
        """Query the delay state pattern.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_delay_stop_condition(self) -> None:
        """Set the delay stop condition.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_delay_stop_condition(self) -> None:
        """Query the delay stop condition.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_delay_time_method(self) -> None:
        """Set the delay time method.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_delay_time_method(self) -> None:
        """Query the delay time method.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    # --- DISPlay commands ---

    # --- IEEE488.2 common commands ---

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
        number : {1 - 9}
            Buffer number, 1 =< number =< 9.
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
        number : {1 - 9}
            Buffer number, 1 =< number =< 9.
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

    # --- INITiate command ---

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
        rated ouptut. This method always uses NSELect because fewer characters are
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

    # --- MMEMory commands ---

    # --- MONItor commands ---

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

    def get_ocp_value(self, channel: int | None = None) -> float:
        """Get the overcurrent protection value for a channel.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        value : float
            Overcurrent protection value.
        """
        # TODO: Manual suggests this function can also take MIN and MAX arguments. Test
        # what this does.
        cmd = ":OUTP:OCP:VAL?"
        if channel is not None:
            cmd += f" CH{channel}"

        # TODO: test if float is returned when set to MIN or MAX
        value = float(self._query(cmd))

        return value

    def get_ovp(self, channel: int | None = None) -> bool:
        """Query whether current of a channel has exceeded its OVP value.

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

    def get_ovp_value(self, channel: int | None = None) -> float:
        """Get the overvoltage protection value for a channel.

        The instrument provides two commands to set this function. This method uses
        the `output` command rather than the `source` command.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.

        Returns
        -------
        value : float
            Overvoltage protection value.
        """
        # TODO: Manual suggests this function can also take MIN and MAX arguments. Test
        # what this does.
        cmd = ":OUTP:OVP:VAL?"
        if channel is not None:
            cmd += f" CH{channel}"

        # TODO: test if float is returned when set to MIN or MAX
        value = float(self._query(cmd))

        return value

    def set_output_range(self, range: str) -> None:
        """Only applicable to single channel model.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.

        Parameters
        ----------
        range : str
            Requested output range.
        """
        warnings.warn("Not implemented.")

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

    def set_output_timer(self) -> None:
        """Set the output timer.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_output_timer(self) -> None:
        """Query the output timer.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_output_timer_enable(self) -> None:
        """Set the output timer enable.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_output_timer_enable(self) -> None:
        """Query the output timer enable.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_output_track(self) -> None:
        """Set the output track.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_output_track(self) -> None:
        """Query the output track.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    # --- PRESet commands ---

    # --- RECAll commands ---

    # --- RECorder commands ---

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

    def set_current_step(self) -> None:
        """Set the current step.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_current_step(self) -> None:
        """Query the current step.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_source_trigger(
        self, func: Literal["CURR", "VOLT"], level: float, channel: int | None = None
    ) -> None:
        """Set the source trigger level.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.

        Parameters
        ----------
        func : {'CURR', 'VOLT'}
            Quantity to select: current ('CURR') or voltage ('VOLT').
        level : float
            Requested trigger level for the selected quantity.
        channel : int or None
            One-based physical channel number. Omit to use the selected channel.
        """
        warnings.warn("Not implemented.")

    def get_source_trigger(
        self, func: Literal["CURR", "VOLT"], level: float, channel: int | None = None
    ) -> None:
        """Query the source trigger level.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.

        Parameters
        ----------
        func : {'CURR', 'VOLT'}
            Quantity to select: current ('CURR') or voltage ('VOLT').
        level : float
            Requested trigger level for the selected quantity.
        channel : int or None
            One-based physical channel number. Omit to use the selected channel.
        """
        warnings.warn("Not implemented.")

    def clear_ocp_circuit(self) -> None:
        """Clear the overcurrent protection circuit.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

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
            Channel to select. If omitted, voltagely selected channel is used.
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
            Channel to select. If omitted, voltagely selected channel is used.

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

    def set_voltage_step(self) -> None:
        """Set the voltage step.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_voltage_step(self) -> None:
        """Query the voltage step.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def clear_ovp_circuit(self) -> None:
        """Clear the overvoltage protection circuit.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_voltage_range(self, range: str, channel: int | None = None) -> None:
        """Set the voltage range of a channel.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.

        Only applicable to single channel model.

        Parameters
        ----------
        range : str
            Requested output range.
        channel : int or None
            One-based physical channel number. Omit to use the selected channel.
        """
        warnings.warn("Not implemented.")

    # --- STATus commands ---

    # --- STORe commands ---

    # --- SYSTem commands ---

    def set_beeper(self) -> None:
        """Set the beeper state.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_beeper(self) -> None:
        """Query the beeper state.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_gpib_config(self) -> None:
        """Set the GPIB configuration.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_gpib_config(self) -> None:
        """Query the GPIB configuration.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_lan_config(self) -> None:
        """Set the LAN configuration.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_lan_config(self) -> None:
        """Query the LAN configuration.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_rs232_config(self) -> None:
        """Set the RS232 configuration.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_rs232_config(self) -> None:
        """Query the RS232 configuration.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_contrast(self) -> None:
        """Set the contrast.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_contrast(self) -> None:
        """Query the contrast.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_errors(self, *, _resource: MessageBasedResource | None = None) -> list[str]:
        """Read and remove queued errors until the instrument reports no error.

        Error responses are returned unchanged, excluding the final zero-code
        response. Direct VISA queries avoid recursive automatic error checks.
        The configured VISA timeout and query delay are used without overrides.

        Parameters
        ----------
        _resource : MessageBasedResource, optional
            Internal connection-initialization resource, used before publishing
            the connection. Normally omitted to read this driver's instrument.

        Returns
        -------
        errors : list of str
            Raw nonzero error responses, or an empty list when no errors exist.
        """
        resource = self._instr if _resource is None else _resource
        if resource is None:
            raise RuntimeError(NOT_CONNECTED_MESSAGE)
        errors: list[str] = []
        while True:
            response = resource.query(":SYST:ERR?")
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

    def set_key_keylock(self) -> None:
        """Set the individual front-panel key lock.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_key_keylock(self) -> None:
        """Query the individual front-panel key lock.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

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

    def set_language(self) -> None:
        """Set the language.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_language(self) -> None:
        """Query the language.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_local(self) -> None:
        """Return instrument to local mode."""
        self._write(":SYST:LOC")

    def set_lock(self) -> None:
        """Set the instrument lock state.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_lock(self) -> None:
        """Query the instrument lock state.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_on_off_sync(self) -> None:
        """Set the output synchronization.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_on_off_sync(self) -> None:
        """Query the output synchronization.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_otp_enable(self) -> None:
        """Set the overtemperature protection enable state.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_otp_enable(self) -> None:
        """Query the overtemperature protection enable state.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_power_on_config_mode(self) -> None:
        """Set the power on config mode.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_power_on_config_mode(self) -> None:
        """Query the power on config mode.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_remote(self) -> None:
        """Switch to remote mode and restrict front-panel operations.

        Call after connect() when desired. This explicit mode change checks
        the instrument error queue like other commands.
        """
        self._write(":SYST:REM")

    def set_brightness(self) -> None:
        """Set the brightness.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_brightness(self) -> None:
        """Query the brightness.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def set_screen_saver_enable(self) -> None:
        """Set the screen saver enable.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

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

    def set_track_mode(self) -> None:
        """Set the tracking mode.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_track_mode(self) -> None:
        """Query the tracking mode.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    def get_scpi_version(self) -> None:
        """Query the SCPI version.

        This operation is not implemented. A warning is emitted and no
        instrument command is sent.
        """
        warnings.warn("Not implemented.")

    # --- TIMEr commands ---

    # --- TRIGger commands ---
