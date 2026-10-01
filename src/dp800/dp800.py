# SPDX-License-Identifier: GPL-3.0-or-later

"""Rigol DP800 series power supply control library.

The full instrument manual, including the programming guide, can be found at
https://www.rigolna.com/products/dc-power-loads/dp800/.
"""

import logging
import warnings
from types import MappingProxyType
from typing import Any, Final, Literal

import pyvisa
from pyvisa.resources import MessageBasedResource, Resource

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

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class dp800:
    """Rigol DP800 series power supply instrument.

    Use connect() to initialize a connection and disconnect() to release it.
    The VISA resource is held internally as _instr.
    """

    def __init__(self) -> None:
        self._instr: MessageBasedResource | None = None

    def _get_instr(self) -> MessageBasedResource:
        """Return the connected resource or raise before attempting I/O."""
        if self._instr is None:
            raise RuntimeError("Instrument is not connected.")
        return self._instr

    def connect(
        self,
        resource_name: str,
        *,
        resource_manager: pyvisa.ResourceManager | None = None,
        **resource_kwargs: Any,
    ) -> None:
        """Open and initialize a connection without resetting the instrument.

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
            and resource attributes such as timeout. Attributes are applied
            after opening so failures can close the resource. This driver uses
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

        Notes
        -----
        Remote mode and the identity query must succeed before _instr is assigned.
        On failure the resource is closed and the instance stays disconnected.
        No reset, voltage/current setting, or output-enable command is sent.
        PyVISA can reuse a manager for the same backend. This driver closes only
        its instrument resource. The PyVISA resource retains its manager for
        the connection's lifetime.
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
        opening_options = {
            key: resource_kwargs.pop(key)
            for key in ("access_mode", "open_timeout", "resource_pyclass")
            if key in resource_kwargs
        }
        manager = (
            pyvisa.ResourceManager() if resource_manager is None else resource_manager
        )
        resource: Resource | None = None
        try:
            resource = manager.open_resource(resource_name, **opening_options)
            if not isinstance(resource, MessageBasedResource):
                raise TypeError("DP800 requires a message-based VISA resource.")
            for key, value in resource_kwargs.items():
                # Attributes cannot replace I/O methods or bypass protocol settings.
                if (
                    key.startswith("_")
                    or not hasattr(resource, key)
                    or callable(getattr(resource, key))
                ):
                    raise ValueError(f"{key!r} is not a valid resource attribute.")
                setattr(resource, key, value)
            resource.write(":SYST:REM")
            identity = resource.query("*IDN?")
            logger.info("%s connected!", identity)
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
                    resource.write(command)
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

        self._get_instr().write(cmd)

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
            resp = float(self._get_instr().query(cmd))

            return resp
        elif (channel is None) & (function is not None):
            warnings.warn(
                "When querying using APPL? you may omit both `channel` and `function` parameters or `function` only. You cannot only omit `channel`."
            )
            cmd += f",{function}"
            return self._get_instr().query(cmd)
        else:
            ch, rating, voltage, current = self._get_instr().query(cmd).split(",")

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

        self._get_instr().write(cmd)

    def get_delay_cycles(self) -> str | tuple[str, int]:
        """Get the number of cycles for the delayer.

        Returns
        -------
        resp : str or tuple of str and int
            Formatted number of cycles for the delayer. Can be 'I' or tuple comprised of
            'N' and and integer representing the number of cycles.
        """
        cmd = ":DELAY:CYCLE?"
        resp = self._get_instr().query(cmd).split(",")

        if len(resp) == 1:
            return resp[0]
        else:
            return resp[0], int(resp[1])

    def set_delay_end_state(self, endstate: Literal["ON", "OFF", "LAST"]) -> None:
        """Set the state of the instrument when the delayer stops.

        Parameters
        ----------
        endstate : 'ON', 'OFF', 'LAST'
            State to put instrument in when delayer stops. 'ON' switches on the output,
            'OFF' switches off the output, and 'LAST' uses the last state.
        """
        cmd = f":DELAY:ENDS {endstate}"
        self._get_instr().write(cmd)

    def get_delay_end_state(self) -> str:
        """Get the state of the instrument when the delayer stops.

        Returns
        -------
        endstate : 'ON', 'OFF', 'LAST'
            State to put instrument in when delayer stops. 'ON' switches on the output,
            'OFF' switches off the output, and 'LAST' uses the last state.
        """
        cmd = ":DELAY:ENDS?"
        endstate = self._get_instr().query(cmd)

        return endstate

    def set_delay_groups(self, groups: int) -> None:
        """Set the number of output groups of the delayer.

        Parameters
        ----------
        groups : int
            Number of output groups of delayer cycles, i.e. number of times output
            turns on or off. Must be in range 1-2048.
        """
        cmd = f":DELAY:GROUP {groups}"
        self._get_instr().write(cmd)

    def get_delay_groups(self) -> int:
        """Get the number of output groups of the delayer.

        Returns
        -------
        groups : int
            Number of output groups of delayer cycles, i.e. number of times output
            turns on or off.
        """
        cmd = f":DELAY:GROUP?"
        groups = int(self._get_instr().query(cmd))

        return groups

    def set_delay_parameters(self) -> None:
        """Set the delayer parameters of the specified group."""
        warnings.warn("Not implemented.")

    def get_delay_parameters(self) -> None:
        """Get the delayer parameters of the specified group."""
        warnings.warn("Not implemented.")

    def set_delay_state(self, enable: bool) -> None:
        """Enable/disable the delay output function.

        Applies to currently selected channel.

        Parameters
        ----------
        """
        warnings.warn("Not implemented.")

    def get_delay_state(self, enable: bool) -> None:
        """Get the enable/disable state of the delay output function.

        Applies to current channel.
        """
        warnings.warn("Not implemented.")

    def set_delay_state_pattern(self) -> None:
        warnings.warn("Not implemented.")

    def get_delay_state_pattern(self) -> None:
        warnings.warn("Not implemented.")

    def set_delay_stop_condition(self) -> None:
        warnings.warn("Not implemented.")

    def get_delay_stop_condition(self) -> None:
        warnings.warn("Not implemented.")

    def set_delay_time_method(self) -> None:
        warnings.warn("Not implemented.")

    def get_delay_time_method(self) -> None:
        warnings.warn("Not implemented.")

    # --- DISPlay commands ---

    # --- IEEE488.2 common commands ---

    def clear_event_registers(self) -> None:
        """Clear all event registers."""
        self._get_instr().write("*CLS")

    def set_standard_event_enable_register(self, value: int) -> None:
        """Enable bits in the standard event enable register.

        Parameters
        ----------
        value : int
            Decimal value of the enable register corresponding to the sum of binary
            weights of the bits to be enabled, e.g. to enable bits 1 and 3 only would
            require setting the value to 2^1 + 2^3 = 10. Must be in range 0 - 255.
        """
        if (value >= 0) & (value <= 255):
            self._get_instr().write(f"*ESE {value}")
        else:
            raise ValueError(f"Value: {value} is out of range. Must be in range 0-255.")

    def get_standard_event_enable_register(self) -> int:
        """Get the standard event enable register value.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self._get_instr().query("*ESE?"))

        return value

    def get_standard_event_register(self) -> int:
        """Get the standard event register value.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self._get_instr().query("*ESR?"))

        return value

    def get_id(self) -> list[str]:
        """Get instrument identity string.

        Returns
        -------
        id : list of str
            List of identification strings consisting of manufacturer, model, serial
            number, and board version number in order.
        """
        idn = self._get_instr().query("*IDN?").split(",")

        return idn

    def set_opc(self) -> None:
        """Set operation complete.

        Sets bit 0 of the standard event register after completing the current
        operation.
        """
        self._get_instr().write("*OPC")

    def get_opc(self) -> int:
        """Query whether current operation is complete.

        Returns
        -------
        opc : int
            Binary value representing the completion state of the current command:

                * 0 : incomplete
                * 1 : complete
        """
        opc = int(self._get_instr().query("*OPC?"))

        return opc

    def get_option_installation_status(self) -> str:
        """Get the status of installed options.

        Returns
        -------
        options : str
            List of options. If an option is installed its name is returned, otherwise
            the query returns a 0.
        """
        options = self._get_instr().query("*OPT")

        return options

    def set_power_on_status_clear_bit(self, value: int) -> None:
        """Set the power-on status clear bit.

        Parameters
        ----------
        value : {0, 1}
            Value of power-on status clear bit. Values:

                * 0 : Cleared, status enable registers maintain values at power down.
                * 1 : Set, all status and enable registers are cleared on power up.
        """
        cmd = f"*PSC {value}"
        self._get_instr().write(cmd)

    def get_power_on_status_clear_bit(self) -> int:
        """Get the power-on status clear bit.

        Returns
        -------
        value : int
            Value of power-on status clear bit. Values:

                * 0 : Cleared, status enable registers maintain values at power down.
                * 1 : Set, all status and enable registers are cleared on power up.
        """
        cmd = f"*PSC?"
        value = int(self._get_instr().query(cmd))

        return value

    def recall_setup(self, number: int) -> None:
        """Recall instrument setup from setting buffer.

        Parameters
        ----------
        number : {1 - 9}
            Buffer number, 1 =< number =< 9.
        """
        cmd = f"*RCL {number}"
        self._get_instr().write(cmd)

    def reset(self) -> None:
        """Reset the instrument to the factory default configuration."""
        cmd = f"*RST"
        self._get_instr().write(cmd)

    def save_setup(self, number: int) -> None:
        """Save the instrument setup in a settings buffer.

        Parameters
        ----------
        number : {1 - 9}
            Buffer number, 1 =< number =< 9.
        """
        cmd = f"*SAV {number}"
        self._get_instr().write(cmd)

    def set_status_byte_enable_register(self, value: int) -> None:
        """Enable bits in the status byte enable register.

        Parameters
        ----------
        value : int
            Decimal value of the enable register corresponding to the sum of binary
            weights of the bits to be enabled, e.g. to enable bits 1 and 3 only would
            require setting the value to 2^1 + 2^3 = 10. Must be in range 0 - 255.
        """
        if (value >= 0) & (value <= 255):
            self._get_instr().write(f"*SRE {value}")
        else:
            raise ValueError(f"Value: {value} is out of range. Must be in range 0-255.")

    def get_status_byte_enable_register(self) -> int:
        """Get the status byte enable register value.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self._get_instr().query("*SRE?"))

        return value

    def get_status_byte_register(self) -> int:
        """Get the status byte register value.

        Querying this register does not clear it.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self._get_instr().query("*STB?"))

        return value

    def trigger(self) -> None:
        """Generate a trigger.

        Only available when bus (software) trigger is selected.
        """
        self._get_instr().write("*TRG")

    def get_self_test_results(self) -> list[str]:
        """Get the results of the instrument self-test.

        Returns
        -------
        result : list
            List of test results for the top board, bottom board, and fan.
        """
        result = self._get_instr().query("*TST?").split(",")

        return result

    def wait(self) -> None:
        """Wait until processing all pending commands is complete."""
        self._get_instr().write("*WAI")

    # --- INITiate command ---

    def init_trigger(self) -> None:
        """Initialise the trigger system."""
        cmd = ":INIT"
        self._get_instr().write(cmd)

    # --- INSTrument commands ---

    def set_trigger_coupling_channels(self, channels: str | list[str]) -> None:
        """Set trigger coupling channels.

        Only applicable to multi-channel models.

        Parameters
        ----------
        channels : 'ALL', 'NONE', or list containing 'CH1', 'CH2', 'CH3'
            Trigger coupling channels. If list, should contain at least two channels.
        """
        cmd = ":INST:COUP "
        cmd += ",".join(channels) if isinstance(channels, list) else channels
        self._get_instr().write(cmd)

    def get_trigger_coupling_channels(self) -> str | list[str]:
        """Get trigger coupling channels.

        Only applicable to multi-channel models.

        Returns
        -------
        channels : str or list
            If 'ALL' or 'NONE' that string is returned. Otherwise query returns a list
            where each element is a channel name and rating separated by a `:`.
        """
        channels = self._get_instr().query(":INST:COUP?").split(",")
        if len(channels) == 1:
            return channels[0]

        return channels

    def set_channel(self, channel: int) -> None:
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
        self._get_instr().write(f":INST CH{channel}")

    def get_channel(self) -> int:
        """Get the currently selected channel.

        Only applicable to multi-channel models.

        The instrument provides two functions for this: NSELct and SELect. NSELect
        returns a bare number, e.g. 2, whereas SELect returns a channel name and
        rated ouptut. This method always uses NSELect because fewer characters are
        exchanged in the query operation.

        Parameters
        ----------
        channel : int
            Channel number.
        """
        channel = int(self._get_instr().query(":INST:NSEL?"))

        return channel

    # --- LIC commands ---

    def install_options(self, options_licence: str) -> None:
        """Install options.

        Only applicable to DP831/DP832/DP821/DP811.

        Parameters
        ----------
        options_licence : str
            Unique 28-byte ASCII string only including English letters and numbers.
        """
        self._get_instr().write(f":LIC:SET {options_licence}")

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
        values = self._get_instr().query(cmd).split(",")
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
        mode = self._get_instr().query(cmd)

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
        response = self._get_instr().query(cmd)
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
        self._get_instr().write(cmd)

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
        self._get_instr().write(cmd)

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
        response = self._get_instr().query(cmd)
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
        self._get_instr().write(cmd)

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
        value = float(self._get_instr().query(cmd))

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
        response = self._get_instr().query(cmd)
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
        self._get_instr().write(cmd)

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
        self._get_instr().write(cmd)

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
        response = self._get_instr().query(cmd)
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
        self._get_instr().write(cmd)

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
        value = float(self._get_instr().query(cmd))

        return value

    def set_output_range(self, range: str) -> None:
        """Only applicable to single channel model."""
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
        self._get_instr().write(cmd)

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
        response = self._get_instr().query(cmd)
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
        self._get_instr().write(cmd)

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
        cmd = ":OUTP"
        if channel is not None:
            cmd += f" CH{channel}"
        response = self._get_instr().query(cmd)
        return response == "ON"

    def set_output_timer(self) -> None:
        warnings.warn("Not implemented.")

    def get_output_timer(self) -> None:
        warnings.warn("Not implemented.")

    def set_output_timer_enable(self) -> None:
        warnings.warn("Not implemented.")

    def get_output_timer_enable(self) -> None:
        warnings.warn("Not implemented.")

    def set_output_track(self) -> None:
        warnings.warn("Not implemented.")

    def get_output_track(self) -> None:
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
        self._get_instr().write(cmd)

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
        current = float(self._get_instr().query(cmd))

        return current

    def set_current_step(self) -> None:
        warnings.warn("Not implemented.")

    def get_current_step(self) -> None:
        warnings.warn("Not implemented.")

    def set_source_trigger(
        self, func: Literal["CURR", "VOLT"], level: float, channel: int | None = None
    ) -> None:
        warnings.warn("Not implemented.")

    def get_source_trigger(
        self, func: Literal["CURR", "VOLT"], level: float, channel: int | None = None
    ) -> None:
        warnings.warn("Not implemented.")

    def clear_ocp_circuit(self) -> None:
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
        self._get_instr().write(cmd)

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
        voltage = float(self._get_instr().query(cmd))

        return voltage

    def set_voltage_step(self) -> None:
        warnings.warn("Not implemented.")

    def get_voltage_step(self) -> None:
        warnings.warn("Not implemented.")

    def clear_ovp_circuit(self) -> None:
        warnings.warn("Not implemented.")

    def set_voltage_range(self, range: str, channel: int | None = None) -> None:
        """Set the voltage range of a channel.

        Only applicable to single channel model.
        """
        warnings.warn("Not implemented.")

    # --- STATus commands ---

    # --- STORe commands ---

    # --- SYSTem commands ---

    def set_beeper(self) -> None:
        warnings.warn("Not implemented.")

    def get_beeper(self) -> None:
        warnings.warn("Not implemented.")

    def set_gpib_config(self) -> None:
        warnings.warn("Not implemented.")

    def get_gpib_config(self) -> None:
        warnings.warn("Not implemented.")

    def set_lan_config(self) -> None:
        warnings.warn("Not implemented.")

    def get_lan_config(self) -> None:
        warnings.warn("Not implemented.")

    def set_rs232_config(self) -> None:
        warnings.warn("Not implemented.")

    def get_rs232_config(self) -> None:
        warnings.warn("Not implemented.")

    def set_contrast(self) -> None:
        warnings.warn("Not implemented.")

    def get_contrast(self) -> None:
        warnings.warn("Not implemented.")

    def get_error(self) -> None:
        """Query and clear error messages in the error queue.

        Returns
        -------
        error : list
            Error code and error message.
        """
        # code, msg = self._get_instr().query(":SYST:ERR").split(",")
        # code = int(code)
        # if code != 0:
        #     warnings.warn(f"Instrument error: {code}, {msg}")
        warnings.warn("Not implemented.")

    def set_key_keylock(self) -> None:
        warnings.warn("Not implemented.")

    def get_key_keylock(self) -> None:
        warnings.warn("Not implemented.")

    def set_keylock_enable(self, enable: bool) -> None:
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
        self._get_instr().write(cmd)

    def get_keylock_enable(self) -> bool:
        """Querey enable/disable state of front panel keys in remote mode.

        Returns
        -------
        enable : bool
            Enabled/disabled state of the front panel lock
        """
        cmd = ":SYST:KLOC:STAT?"
        response = self._get_instr().query(":SYST:KLOC:STAT?")
        return response == "ON"

    def set_language(self) -> None:
        warnings.warn("Not implemented.")

    def get_language(self) -> None:
        warnings.warn("Not implemented.")

    def set_local(self) -> None:
        """Return instrument to local mode."""
        self._get_instr().write(":SYST:LOC")

    def set_lock(self) -> None:
        warnings.warn("Not implemented.")

    def get_lock(self) -> None:
        warnings.warn("Not implemented.")

    def set_on_off_sync(self) -> None:
        warnings.warn("Not implemented.")

    def get_on_off_sync(self) -> None:
        warnings.warn("Not implemented.")

    def set_otp_enable(self) -> None:
        warnings.warn("Not implemented.")

    def get_otp_enable(self) -> None:
        warnings.warn("Not implemented.")

    def set_power_on_config_mode(self) -> None:
        warnings.warn("Not implemented.")

    def get_power_on_config_mode(self) -> None:
        warnings.warn("Not implemented.")

    def set_remote(self) -> None:
        """Set the instrument to remote mode."""
        self._get_instr().write(":SYST:REM")

    def set_brightness(self) -> None:
        warnings.warn("Not implemented.")

    def get_brightness(self) -> None:
        warnings.warn("Not implemented.")

    def set_screen_saver_enable(self) -> None:
        warnings.warn("Not implemented.")

    def get_temperature_test_result(self) -> float:
        """Query the self-test result of the temperature.

        Returns
        -------
        temperature : float
            Temperature in degrees celcius.
        """
        temperature = float(self._get_instr().query(":SYST:SELF:TEST:TEMP?"))

        return temperature

    def set_track_mode(self) -> None:
        warnings.warn("Not implemented.")

    def get_track_mode(self) -> None:
        warnings.warn("Not implemented.")

    def get_scpi_version(self) -> None:
        warnings.warn("Not implemented.")

    # --- TIMEr commands ---

    # --- TRIGger commands ---
