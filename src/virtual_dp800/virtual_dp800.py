# SPDX-License-Identifier: GPL-3.0-or-later

"""Virtual Rigol DP800 series power supply control library."""

import logging
import warnings
from collections.abc import Mapping
from types import MappingProxyType, TracebackType
from typing import Any, Literal

import pyvisa

from dp800.dp800 import PROTOCOL_RESOURCE_SETTINGS
from dp800.channel import DP800Channel

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class dp800:
    """Virtual Rigol DP800 series power supply instrument."""

    def __init__(self, check_errors: bool = True) -> None:
        """Initialise object.

        Parameters
        ----------
        check_errors : bool, optional
            Check instrument error status after every command.
        """
        self._connected = False
        self._channels = {channel: DP800Channel(self, channel) for channel in (1, 2, 3)}

    @property
    def channel_count(self) -> int:
        """Return three placeholder channels without hardware I/O."""
        return 3

    @property
    def channels(self) -> Mapping[int, DP800Channel]:
        """Read-only, one-based channel mapping with stable placeholder objects."""
        return MappingProxyType(self._channels)

    def __enter__(self) -> "dp800":
        """Return this instance without opening a connection."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Disconnect on exit without suppressing exceptions from the block."""
        self.disconnect()

    def connect(
        self,
        resource_name: str,
        *,
        resource_manager: pyvisa.ResourceManager | None = None,
        **resource_kwargs: Any,
    ) -> None:
        """Connect virtually, without opening hardware or resetting state.

        Parameters
        ----------
        resource_name : str
            Full VISA resource name, e.g. "ASRL2::INSTR", "GPIB0::14::INSTR" etc. See
            https://pyvisa.readthedocs.io/en/latest/introduction/names.html for more
            info on correct formatting for resource names.
        resource_manager : pyvisa.ResourceManager, optional
            Accepted for compatibility with the hardware driver, but never used,
            retained, or closed. No manager is created by the virtual driver.
        resource_kwargs : dict
            Accepted for compatibility with the hardware driver. Conflicting
            encoding/termination values emit a warning and are ignored in favor
            of the driver-owned constants.
            Other values are ignored by this placeholder implementation.

        Raises
        ------
        RuntimeError
            If already connected. Disconnect before connecting again.
        """
        if self._connected:
            raise RuntimeError("Already connected; disconnect before reconnecting.")
        for key, required in PROTOCOL_RESOURCE_SETTINGS.items():
            if key in resource_kwargs and resource_kwargs[key] != required:
                warnings.warn(
                    f"The driver owns {key}; the supplied value "
                    f"{resource_kwargs[key]!r} will be ignored. Using {required!r}.",
                    stacklevel=2,
                )
        self._connected = True

    def disconnect(self) -> None:
        """Disconnect virtually; repeated calls are harmless."""
        self._connected = False

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

        # cmd = ":APPL "

        # # TODO: test what happens if channel is None on multi-channel instrument
        # if channel is not None:
        #     cmd += f"CH{channel},"

        # # this function can be used to set voltage only
        # if voltage is not None:
        #     cmd += f"{voltage}"

        # # this function can't be used to set current only
        # if {voltage is not None} & {current is not None}:
        #     cmd += f",{current}"

        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def get_apply(
        self,
        channel: int | None = None,
        function: Literal["CURR", "VOLT"] | None = None,
    ) -> float:
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
        # cmd = ":APPL?"

        # if channel is not None:
        #     cmd += f" CH{channel}"

        # # channel cannot be omitted on its own. If channel is omitted, function also
        # # has to be omitted.
        # if (channel is not None) & (function is not None):
        #     cmd += f",{function}"
        #     resp = float(self._instr.query(cmd))

        #     if self.check_errors is True:
        #         self.get_error()

        #     return resp
        # elif (channel is None) & (function is not None):
        #     warnings.warn(
        #         "When querying using APPL? you may omit both `channel` and `function` parameters or `function` only. You cannot only omit `channel`."
        #     )
        #     cmd += f",{function}"
        #     resp = self._instr.query(cmd)

        #     if self.check_errors is True:
        #         self.get_error()

        #     return resp
        # else:
        #     ch, rating, voltage, current = self._instr.query(cmd).split(",")

        #     if self.check_errors is True:
        #         self.get_error()

        #     return ch, rating, float(voltage), float(current)
        return 0.0

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
        # cmd = f":DELAY:CYCLE {finite}"

        # if (finite == "N") & (cycles is not None):
        #     cmd += f",{cycles}"

        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def get_delay_cycles(self) -> str:
        """Get the number of cycles for the delayer.

        Returns
        -------
        resp : str or list
            Formatted number of cycles for the delayer. Can be 'I' or list comprised of
            'N' and and integer representing the number of cycles.
        """
        # cmd = ":DELAY:CYCLE?"
        # resp = self._instr.query(cmd).split(",")

        # if self.check_errors is True:
        #     self.get_error()

        # if len(resp) == 1:
        #     return resp[0]
        # else:
        #     return resp[0], int(resp[1])
        return ""

    @property
    def delay_end_state(self) -> str:
        """Get the state of the instrument when the delayer stops.

        Returns
        -------
        endstate : 'ON', 'OFF', 'LAST'
            State to put instrument in when delayer stops. 'ON' switches on the output,
            'OFF' switches off the output, and 'LAST' uses the last state.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O; assignments are no-ops.
        """
        # cmd = ":DELAY:ENDS?"
        # endstate = self._instr.query(cmd)

        # if self.check_errors is True:
        #     self.get_error()

        # return endstate
        return ""

    @delay_end_state.setter
    def delay_end_state(self, endstate: Literal["ON", "OFF", "LAST"]) -> None:
        """Set the state of the instrument when the delayer stops.

        Parameters
        ----------
        endstate : 'ON', 'OFF', 'LAST'
            State to put instrument in when delayer stops. 'ON' switches on the output,
            'OFF' switches off the output, and 'LAST' uses the last state.
        """
        # cmd = f":DELAY:ENDS {endstate}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    @property
    def delay_groups(self) -> int:
        """Get the number of output groups of the delayer.

        Returns
        -------
        groups : int
            Number of output groups of delayer cycles, i.e. number of times output
            turns on or off.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O; assignments are no-ops.
        The instrument supports group counts in the range 1 - 2048.
        """
        # cmd = f":DELAY:GROUP?"
        # groups = int(self._instr.query(cmd))

        # if self.check_errors is True:
        #     self.get_error()

        # return groups
        return 0

    @delay_groups.setter
    def delay_groups(self, groups: int) -> None:
        """Set the number of output groups of the delayer.

        Parameters
        ----------
        groups : int
            Number of output groups of delayer cycles, i.e. number of times output
            turns on or off. Must be in range 1-2048.
        """
        # cmd = f":DELAY:GROUP {groups}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def set_delay_parameters(self) -> None:
        """Set the delayer parameters of the specified group."""
        pass

    def get_delay_parameters(self) -> None:
        """Get the delayer parameters of the specified group."""
        pass

    def set_delay_state(self, enable: bool) -> None:
        """Enable/disable the delay output function.

        Applies to currently selected channel.

        Parameters
        ----------
        """
        pass

    def get_delay_state(self, enable: bool) -> None:
        """Get the enable/disable state of the delay output function.

        Applies to current channel.
        """
        pass

    def set_delay_state_pattern(self) -> None:
        pass

    def get_delay_state_pattern(self) -> None:
        pass

    def set_delay_stop_condition(self) -> None:
        pass

    def get_delay_stop_condition(self) -> None:
        pass

    def set_delay_time_method(self) -> None:
        pass

    def get_delay_time_method(self) -> None:
        pass

    # --- DISPlay commands ---

    # --- IEEE488.2 common commands ---

    def clear_event_registers(self) -> None:
        """Clear all event registers."""
        # self._instr.write("*CLS")

        # if self.check_errors is True:
        #     self.get_error()
        pass

    @property
    def standard_event_enable_register(self) -> int:
        """Get the standard event enable register value.

        Returns
        -------
        value : int
            Register bitmask in the range 0 - 255; assign to enable bits.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O; assignments are no-ops.
        """
        # value = int(self._instr.query("*ESE?"))

        # if self.check_errors is True:
        #     self.get_error()

        # return value
        return 0

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
        # if (value >= 0) & (value <= 255):
        #     self._instr.write(f"*ESE {value}")
        # else:
        #     raise ValueError(f"Value: {value} is out of range. Must be in range 0-255.")
        pass

    def get_standard_event_register(self) -> int:
        """Get the standard event register value.

        Returns
        -------
        value : int
            Register value.
        """
        # value = int(self._instr.query("*ESR?"))

        # return value
        return 0

    @property
    def identity(self) -> str:
        """Get the virtual instrument identity.

        Returns
        -------
        identity : str
            Fixed identity string for the virtual instrument.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O.
        """
        # idn = self._instr.query("*IDN?").split(",")

        # if self.check_errors is True:
        #     self.get_error()

        # return idn
        return "Virtual Rigol DP800"

    def set_opc(self) -> None:
        """Set operation complete.

        Sets bit 0 of the standard event register after completing the current
        operation.
        """
        # self._instr.write("*OPC")

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def get_opc(self) -> int:
        """Query whether current operation is complete.

        Returns
        -------
        opc : int
            Binary value representing the completion state of the current command:

                * 0 : incomplete
                * 1 : complete
        """
        # opc = int(self._instr.query("*OPC?"))

        # if self.check_errors is True:
        #     self.get_error()

        # return opc
        return 0

    @property
    def option_installation_status(self) -> list[str]:
        """Get the status of installed options.

        Returns
        -------
        options : list of str
            List of options. If an option is installed its name is returned, otherwise
            the query returns a 0.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O.
        """
        # options = self._instr.query("*OPT?")

        # if self.check_errors is True:
        #     self.get_error()

        # return options
        return [""]

    @property
    def power_on_status_clear_bit(self) -> int:
        """Get the power-on status clear bit.

        Returns
        -------
        value : int
            Value of power-on status clear bit. Values:

                * 0 : Cleared, status enable registers maintain values at power down.
                * 1 : Set, all status and enable registers are cleared on power up.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O; assignments are no-ops.
        """
        # cmd = f"*PSC?"
        # value = int(self._instr.query(cmd))

        # if self.check_errors is True:
        #     self.get_error()

        # return value
        return 0

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
        # cmd = f"*PSC {value}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def recall_setup(self, number: int) -> None:
        """Recall instrument setup from setting buffer.

        Parameters
        ----------
        number : {1 - 9}
            Buffer number, 1 =< number =< 9.
        """
        # cmd = f"*RCL {number}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def reset(self) -> None:
        """Reset the instrument to the factory default configuration."""
        # cmd = f"*RST"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def save_setup(self, number: int) -> None:
        """Save the instrument setup in a settings buffer.

        Parameters
        ----------
        number : {1 - 9}
            Buffer number, 1 =< number =< 9.
        """
        # cmd = f"*SAV {number}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    @property
    def status_byte_enable_register(self) -> int:
        """Get the status byte enable register value.

        Returns
        -------
        value : int
            Register bitmask in the range 0 - 255; assign to enable bits.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O; assignments are no-ops.
        """
        # value = int(self._instr.query("*SRE?"))

        # return value
        return 0

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
        # if (value >= 0) & (value <= 255):
        #     self._instr.write(f"*SRE {value}")
        # else:
        #     raise ValueError(f"Value: {value} is out of range. Must be in range 0-255.")
        pass

    @property
    def status_byte_register(self) -> int:
        """Get the status byte register value.

        Querying this register does not clear it.

        Returns
        -------
        value : int
            Register value.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O.
        """
        # value = int(self._instr.query("*STB?"))

        # return value
        return 0

    def trigger(self) -> None:
        """Generate a trigger.

        Only available when bus (software) trigger is selected.
        """
        # self._instr.write("*TRG")

        # if self.check_errors is True:
        #     self.get_error()
        pass

    @property
    def self_test_results(self) -> list[str]:
        """Get the results of the instrument self-test.

        Returns
        -------
        result : list
            List of test results for the top board, bottom board, and fan.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O.
        """
        # result = self._instr.query("*TST?").split(",")

        # if self.check_errors is True:
        #     self.get_error()

        # return result
        return []

    def wait(self) -> None:
        """Wait until processing all pending commands is complete."""
        # self._instr.write("*WAI")

        # if self.check_errors is True:
        #     self.get_error()
        pass

    # --- INITiate command ---

    def init_trigger(self) -> None:
        """Initialise the trigger system."""
        # cmd = ":INIT"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    # --- INSTrument commands ---

    @property
    def trigger_coupling_channels(self) -> str:
        """Get trigger coupling channels.

        Only applicable to multi-channel models.

        Returns
        -------
        channels : str or list
            If 'ALL' or 'NONE' that string is returned. Otherwise query returns a list
            where each element is a channel name and rating separated by a `:`.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O; assignments are no-ops.
        Assign "ALL", "NONE", or a list of at least two channel names.
        """
        # channels = self._instr.query(":INST:COUP?").split(",")
        # if len(channels) == 1:
        #     channels = channels[0]

        # if self.check_errors is True:
        #     self.get_error()

        # return channels
        return ""

    @trigger_coupling_channels.setter
    def trigger_coupling_channels(self, channels: str | list[str]) -> None:
        """Set trigger coupling channels.

        Only applicable to multi-channel models.

        Parameters
        ----------
        channels : 'ALL', 'NONE', or list containing 'CH1', 'CH2', 'CH3'
            Trigger coupling channels. If list, should contain at least two channels.
        """
        # cmd = ":INST:COUP "
        # if type(channels) is list:
        #     channels = channels.join(",")
        # cmd += channels
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    @property
    def selected_channel(self) -> int:
        """Get the currently selected channel.

        Only applicable to multi-channel models.

        The instrument provides two functions for this: NSELct and SELect. NSELect
        returns a bare number, e.g. 2, whereas SELect returns a channel name and
        rated ouptut. This method always uses NSELect because fewer characters are
        exchanged in the query operation.

        Returns
        -------
        channel : int
            Currently selected channel number.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O; assignments are no-ops.
        """
        # channel = int(self._instr.query(":INST:NSEL?"))

        # if self.check_errors is True:
        #     self.get_error()

        # return channel
        return 0

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
        # self._instr.write(f":INST CH{channel}")

        # if self.check_errors is True:
        #     self.get_error()
        pass

    # --- LIC commands ---

    def install_options(self, options_licence: str) -> None:
        """Install options.

        Only applicable to DP831/DP832/DP821/DP811.

        Parameters
        ----------
        options_licence : str
            Unique 28-byte ASCII string only including English letters and numbers.
        """
        # self._instr.write(f":LIC:SET {options_licence}")

        # if self.check_errors is True:
        #     self.get_error()
        pass

    # --- MEASure commands ---

    def measure(
        self,
        func: Literal["ALL", "CURR", "POWE", "VOLT"] | None = None,
        channel: int | None = None,
    ) -> float:
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
        values : float or list of float
            Measurement value(s).
        """
        # cmd = f":MEAS"
        # if func is not None:
        #     cmd += f":{func}"
        # cmd += "?"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # values = self._instr.query(cmd).split(",")
        # if len(values) == 1:
        #     values = values[0]

        # if self.check_errors is True:
        #     self.get_error()

        # return values
        return 0.0

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
        # cmd = ":OUTP:MODE?"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # mode = self._instr.query(cmd)

        # if self.check_errors is True:
        #     self.get_error()

        # return mode
        return ""

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
        # cmd = ":OUTP:OCP:ALAR?"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # ocp_alarm = self._instr.query(cmd)
        # if ocp_alarm == "YES":
        #     ocp_alarm = True
        # else:
        #     ocp_alarm = False

        # if self.check_errors is True:
        #     self.get_error()

        # return ocp_alarm
        return False

    def clear_ocp_label(self, channel: int | None = None) -> None:
        """Clear the overcurrent protection alarm label.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        # cmd = ":OUTP:OCP:CLEAR"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # cmd = ":OUTP:OCP "
        # if channel is not None:
        #     cmd += f"CH{channel},"
        # if enable is True:
        #     cmd += "ON"
        # else:
        #     cmd += "OFF"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # cmd = ":OUTP:OCP?"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # enable = self._instr.query(cmd)
        # if enable == "ON":
        #     enable = True
        # else:
        #     enable = False

        # if self.check_errors is True:
        #     self.get_error()

        # return enable
        return False

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
        # cmd = ":OUTP:OCP:VAL "
        # if channel is not None:
        #     cmd += f"CH{channel},"
        # cmd += f"{value}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # # TODO: Manual suggests this function can also take MIN and MAX arguments. Test
        # # what this does.
        # cmd = ":OUTP:OCP:VAL?"
        # if channel is not None:
        #     cmd += f" CH{channel}"

        # # TODO: test if float is returned when set to MIN or MAX
        # value = float(self._instr.query(cmd))

        # if self.check_errors is True:
        #     self.get_error()

        # return value
        return 0.0

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
        # cmd = ":OUTP:OVP:ALAR?"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # ovp_alarm = self._instr.query(cmd)
        # if ovp_alarm == "YES":
        #     ovp_alarm = True
        # else:
        #     ovp_alarm = False

        # if self.check_errors is True:
        #     self.get_error()

        # return ovp_alarm
        return False

    def clear_ovp_label(self, channel: int | None = None) -> None:
        """Clear the overvoltage protection alarm label.

        Parameters
        ----------
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        # cmd = ":OUTP:OVP:CLEAR"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # cmd = ":OUTP:OVP "
        # if channel is not None:
        #     cmd += f"CH{channel},"
        # if enable is True:
        #     cmd += "ON"
        # else:
        #     cmd += "OFF"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # cmd = ":OUTP:OVP?"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # enable = self._instr.query(cmd)
        # if enable == "ON":
        #     enable = True
        # else:
        #     enable = False

        # if self.check_errors is True:
        #     self.get_error()

        # return enable
        return False

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
        # cmd = ":OUTP:OVP:VAL "
        # if channel is not None:
        #     cmd += f"CH{channel},"
        # cmd += f"{value}"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # # TODO: Manual suggests this function can also take MIN and MAX arguments. Test
        # # what this does.
        # cmd = ":OUTP:OVP:VAL?"
        # if channel is not None:
        #     cmd += f" CH{channel}"

        # # TODO: test if float is returned when set to MIN or MAX
        # value = float(self._instr.query(cmd))

        # if self.check_errors is True:
        #     self.get_error()

        # return value
        return 0.0

    def set_output_range(self, range: str) -> None:
        """Only applicable to single channel model."""
        pass

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
        # cmd = ":OUTP:SENS "
        # if channel is not None:
        #     cmd += f"CH{channel},"
        # if enable is True:
        #     cmd += "ON"
        # else:
        #     cmd += "OFF"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # cmd = ":OUTP:SENS?"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # enable = self._instr.query(cmd)
        # if enable == "ON":
        #     enable = True
        # else:
        #     # On models where the function is not supported the instrument returns
        #     # 'NONE'. This is represented by this function as disabled.
        #     enable = False

        # if self.check_errors is True:
        #     self.get_error()

        # return enable
        return False

    def set_output_enable(self, enable: bool, channel: int | None = None) -> None:
        """Enable/disable the output of a channel.

        Parameters
        ----------
        enable : bool
            Enabled/disabled state of the channel output
        channel : int, optional
            Channel to select. If omitted, currently selected channel is used.
        """
        # cmd = ":OUTP "
        # if channel is not None:
        #     cmd += f" CH{channel},"
        # if enable is True:
        #     cmd += "ON"
        # else:
        #     cmd += "OFF"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # cmd = ":OUTP?"
        # if channel is not None:
        #     cmd += f" CH{channel}"
        # enable = self._instr.query(cmd)
        # if enable == "ON":
        #     enable = True
        # else:
        #     enable = False

        # if self.check_errors is True:
        #     self.get_error()

        # return enable
        return False

    def set_output_timer(self) -> None:
        pass

    def get_output_timer(self) -> None:
        pass

    def set_output_timer_enable(self) -> None:
        pass

    def get_output_timer_enable(self) -> None:
        pass

    def set_output_track(self) -> None:
        pass

    def get_output_track(self) -> None:
        pass

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
        # cmd = f":CURR {current}"
        # if channel is not None:
        #     cmd = f":SOUR{channel}" + cmd
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # cmd = ":CURR?"
        # if channel is not None:
        #     cmd = f":SOUR{channel}" + cmd
        # current = float(self._instr.query(cmd))

        # if self.check_errors is True:
        #     self.get_error()

        # return current
        return 0.0

    def set_current_step(self) -> None:
        pass

    def get_current_step(self) -> None:
        pass

    def set_source_trigger(
        self, func: Literal["CURR", "VOLT"], level: float, channel: int | None = None
    ) -> None:
        pass

    def get_source_trigger(
        self, func: Literal["CURR", "VOLT"], level: float, channel: int | None = None
    ) -> None:
        pass

    def clear_ocp_circuit(self) -> None:
        pass

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
        # cmd = f":VOLT {voltage}"
        # if channel is not None:
        #     cmd = f":SOUR{channel}" + cmd
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

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
        # cmd = ":VOLT?"
        # if channel is not None:
        #     cmd = f":SOUR{channel}" + cmd
        # voltage = float(self._instr.query(cmd))

        # if self.check_errors is True:
        #     self.get_error()

        # return voltage
        return 0.0

    def set_voltage_step(self) -> None:
        pass

    def get_voltage_step(self) -> None:
        pass

    def clear_ovp_circuit(self) -> None:
        pass

    def set_voltage_range(self, range: str, channel: int | None = None) -> None:
        """Set the voltage range of a channel.

        Only applicable to single channel model.
        """
        pass

    # --- STATus commands ---

    # --- STORe commands ---

    # --- SYSTem commands ---

    def set_beeper(self) -> None:
        pass

    def get_beeper(self) -> None:
        pass

    def set_gpib_config(self) -> None:
        pass

    def get_gpib_config(self) -> None:
        pass

    def set_lan_config(self) -> None:
        pass

    def get_lan_config(self) -> None:
        pass

    def set_rs232_config(self) -> None:
        pass

    def get_rs232_config(self) -> None:
        pass

    def set_contrast(self) -> None:
        pass

    def get_contrast(self) -> None:
        pass

    def get_error(self) -> list[str]:
        """Query and clear error messages in the error queue.

        Returns
        -------
        error : list
            Error code and error message.
        """
        # code, msg = self._instr.query(":SYST:ERR").split(",")
        # code = int(code)
        # if code != 0:
        #     warnings.warn(f"Instrument error: {code}, {msg}")
        return []

    def set_key_keylock(self) -> None:
        pass

    def get_key_keylock(self) -> None:
        pass

    @property
    def keylock_enabled(self) -> bool:
        """Query enable/disable state of front panel keys in remote mode.

        Returns
        -------
        enable : bool
            Enabled/disabled state of the front panel lock

        Notes
        -----
        Returns a fixed placeholder without hardware I/O; assignments are no-ops.
        """
        # cmd = ":SYST:KLOC:STAT?"
        # enable = self._instr.query(cmd)
        # if enable == "ON":
        #     enable = True
        # else:
        #     enable = False

        # if self.check_errors is True:
        #     self.get_error()

        # return enable
        return False

    @keylock_enabled.setter
    def keylock_enabled(self, enable: bool) -> None:
        """Enable/disable front panel keys in remote mode.

        Parameters
        ----------
        enable : bool
            Enabled/disabled state of the front panel lock
        """
        # cmd = ":SYST:KLOC:STAT "
        # if enable is True:
        #     cmd += "ON"
        # else:
        #     cmd += "OFF"
        # self._instr.write(cmd)

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def set_language(self) -> None:
        pass

    def get_language(self) -> None:
        pass

    def set_local(self) -> None:
        """Return instrument to local mode."""
        # self._instr.write(":SYST:LOC")

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def set_lock(self) -> None:
        pass

    def get_lock(self) -> None:
        pass

    def set_on_off_sync(self) -> None:
        pass

    def get_on_off_sync(self) -> None:
        pass

    def set_otp_enable(self) -> None:
        pass

    def get_otp_enable(self) -> None:
        pass

    def set_power_on_config_mode(self) -> None:
        pass

    def get_power_on_config_mode(self) -> None:
        pass

    def set_remote(self) -> None:
        """Set the instrument to remote mode."""
        # self._instr.write(":SYST:REM")

        # if self.check_errors is True:
        #     self.get_error()
        pass

    def set_brightness(self) -> None:
        pass

    def get_brightness(self) -> None:
        pass

    def set_screen_saver_enable(self) -> None:
        pass

    @property
    def temperature_test_result(self) -> float:
        """Query the self-test result of the temperature.

        Returns
        -------
        temperature : float
            Temperature in degrees Celsius.

        Notes
        -----
        Returns a fixed placeholder without hardware I/O.
        """
        # temperature = float(self._instr.query(":SYST:SELF:TEST:TEMP?"))

        # if self.check_errors is True:
        #     self.get_error()

        # return temperature
        return 0.0

    def set_track_mode(self) -> None:
        pass

    def get_track_mode(self) -> None:
        pass

    def get_scpi_version(self) -> None:
        pass

    # --- TIMEr commands ---

    # --- TRIGger commands ---
