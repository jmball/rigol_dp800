"""Rigol DP800 series power supply control library.

The full instrument manual, including the programming guide, can be found at
https://www.rigolna.com/products/dc-power-loads/dp800/.
"""
import logging
import warnings

import visa


logging.captureWarnings(True)
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

rm = visa.ResourceManager()


class dp800:
    """Rigol DP800 series power supply instrument.

    Use the `connect()` method to open a connection to the instrument and instantiate
    the VISA resource attribute `instr` for an dp800 instance. This attribute can be
    used to access all of the PyVISA attributes and methods for the resource.
    """

    def __init__(self, check_errors=True):
        """Initialise object.

        Parameters
        ----------
        check_errors : bool, optional
            Check instrument error status after every command.
        """
        self.check_errors = check_errors

    def connect(
        self,
        resource_name,
        reset=True,
        set_default_configuration=True,
        **resource_kwargs,
    ):
        """Conntect to the instrument.

        Parameters
        ----------
        resource_name : str
            Full VISA resource name, e.g. "ASRL2::INSTR", "GPIB0::14::INSTR" etc. See
            https://pyvisa.readthedocs.io/en/latest/introduction/names.html for more
            info on correct formatting for resource names.
        reset : bool, optional
            Reset the instrument to the built-in default configuration.
        set_default_configuration : bool, optional
            If True, set all configuration settings to defaults defined in the
            `set_configuraiton` method.
        resource_kwargs : dict
            Keyword arguments to be used to change instrument attributes after
            construction.
        """
        self.instr = rm.open_resource(resource_name, **resource_kwargs)
        if reset is True:
            self.reset()
        if set_default_configuration is True:
            self.set_configuration()

    def disconnect(self):
        """Disconnect the instrument."""
        self.instr.close()

    def set_configuration(self):
        """Set the instrument configuration."""
        pass

    def get_configuration(self):
        """Get the instrument configuration."""
        pass

    def reset(self):
        """Reset the instrument to built-in default configuration."""
        pass

    # --- ANALyser commands ---

    # --- APPLy commands---

    def set_apply(self, channel=None, voltage=None, current=None):
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
            cmd = cmd + f"CH{channel},"

        # this function can be used to set voltage only
        if voltage is not None:
            cmd = cmd + f"{voltage}"

        # this function can't be used to set current only
        if {voltage is not None} & {current is not None}:
            cmd = cmd + f",{current}"

        self.instr.write(cmd)

    def get_apply(self, channel=None, function=None):
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
            cmd = cmd + f" CH{channel}"

        # channel cannot be omitted on its own. If channel is omitted, function also
        # has to be omitted.
        if (channel is not None) & (function is not None):
            cmd = cmd + f"{,function}"
            return float(self.instr.query(cmd))
        elif (channel is None) & (function is not None):
            warning.warn("When querying using APPL? you may omit both `channel` and `function` parameters or `function` only. You cannot only omit `channel`.")
            cmd = cmd + f"{,function}"
            return self.instr.query(cmd)
        else:
            ch, rating, voltage, current = self.instr.query(cmd).split(",")
            return ch, rating, float(voltage), float(current)

    # --- DELAY commands ---

    def set_delay_cycles(self, finite, cycles=None):
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

        if (finite == 'N') & (cycles is not None):
            cmd = cmd + f",{cycles}"

        self.instr.write(cmd)

    def get_delay_cycles(self):
        """Get the number of cycles for the delayer.

        Returns
        -------
        resp : str or list
            Formatted number of cycles for the delayer. Can be 'I' or list comprised of
            'N' and and integer representing the number of cycles.
        """
        cmd = ":DELAY:CYCLE?"
        resp = self.instr.query(cmd).split(",")
        if len(resp) == 1:
            return resp[0]
        else:
            return resp[0], int(resp[1])

    def set_delay_end_state(self, endstate):
        """Set the state of the instrument when the delayer stops.

        Parameters
        ----------
        endstate : 'ON', 'OFF', 'LAST'
            State to put instrument in when delayer stops. 'ON' switches on the output,
            'OFF' switches off the output, and 'LAST' uses the last state.
        """
        cmd = f":DELAY:ENDS {endstate}"
        self.instr.write(cmd)

    def get_delay_end_state(self):
        """Get the state of the instrument when the delayer stops.

        Returns
        -------
        endstate : 'ON', 'OFF', 'LAST'
            State to put instrument in when delayer stops. 'ON' switches on the output,
            'OFF' switches off the output, and 'LAST' uses the last state.
        """
        cmd = ":DELAY:ENDS?"
        endstate = self.instr.query(cmd)
        return endstate

    def set_delay_groups(self, groups):
        """Set the number of output groups of the delayer.

        Parameters
        ----------
        groups : int
            Number of output groups of delayer cycles, i.e. number of times output
            turns on or off. Must be in range 1-2048.
        """
        cmd = f":DELAY:GROUP {groups}"
        self.instr.write(cmd)

    def get_delay_groups(self):
        """Get the number of output groups of the delayer.

        Returns
        -------
        groups : int
            Number of output groups of delayer cycles, i.e. number of times output
            turns on or off.
        """
        cmd = f":DELAY:GROUP?"
        groups = int(self.instr.query(cmd))
        return groups

    def set_delay_parameters(self):
        """Set the delayer parameters of the specified group."""
        pass

    def get_delay_parameters(self):
        """Get the delayer parameters of the specified group."""
        pass

    def set_delay_state(self, enable):
        """Enable/disable the delay output function.

        Applies to currently selected channel.

        Parameters
        ----------
        """
        pass

    def get_delay_state(self, enable):
        """Get the enable/disable state of the delay output function.

        Applies to current channel.
        """
        pass

    def set_delay_state_pattern(self):
        pass

    def get_delay_state_pattern(self):
        pass

    def set_delay_stop_condition(self):
        pass

    def get_delay_stop_condition(self):
        pass

    def set_delay_time_method(self):
        pass

    def get_delay_time_method(self):
        pass

    # --- DISPlay commands ---

    # --- IEEE488.2 common commands ---

    def clear_event_registers(self):
        """Clear all event registers."""
        self.instr.write("*CLS")

    def set_standard_event_enable_register(self, value):
        """Enable bits in the standard event enable register.

        Parameters
        ----------
        value : int
            Decimal value of the enable register corresponding to the sum of binary
            weights of the bits to be enabled, e.g. to enable bits 1 and 3 only would
            require setting the value to 2^1 + 2^3 = 10. Must be in range 0 - 255.
        """
        if (value >= 0) & (value <= 255):
            self.instr.write(f"*ESE {value}")
        else:
            raise ValueError(
                f"Value: {value} is out of range. Must be in range 0-255."
            )

    def get_standard_event_enable_register(self):
        """Get the standard event enable register value.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self.instr.query("*ESE?"))

        return value

    def get_standard_event_register(self):
        """Get the standard event register value.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self.instr.query("*ESR?"))

        return value

    def get_id(self):
        """Get instrument identity string.

        Returns
        -------
        id : list of str
            List of identification strings consisting of manufacturer, model, serial
            number, and board version number in order.
        """
        idn = self.instr.query("*IDN?").split(",")

        return idn

    def set_opc(self):
        """Set operation complete.

        Sets bit 0 of the standard event register after completing the current
        operation.
        """
        self.instr.write("*OPC")

    def get_opc(self):
        """Query whether current operation is complete.

        Returns
        -------
        opc : int
            Binary value representing the completion state of the current command:

                * 0 : incomplete
                * 1 : complete
        """
        return int(self.instr.query("*OPC?"))

    def get_option_installation_status(self):
        """Get the status of installed options.

        Returns
        -------
        options : list of str
            List of options. If an option is installed its name is returned, otherwise
            the query returns a 0.
        """
        options = self.instr.query("*OPT")

        return options

    def set_power_on_status_clear_bit(self, value):
        """Set the power-on status clear bit.

        Parameters
        ----------
        value : {0, 1}
            Value of power-on status clear bit. Values:

                * 0 : Cleared, status enable registers maintain values at power down.
                * 1 : Set, all status and enable registers are cleared on power up.
        """
        cmd = f"*PSC {value}"
        self.instr.write(cmd)

    def get_power_on_status_clear_bit(self):
        """Get the power-on status clear bit.

        Returns
        -------
        value : int
            Value of power-on status clear bit. Values:

                * 0 : Cleared, status enable registers maintain values at power down.
                * 1 : Set, all status and enable registers are cleared on power up.
        """
        cmd = f"*PSC?"
        value = int(self.instr.query(cmd))

        return value

    def recall_setup(self, number):
        """Recall instrument setup from setting buffer.

        Parameters
        ----------
        number : {1 - 9}
            Buffer number, 1 =< number =< 9.
        """
        cmd = f"*RCL {number}"
        self.instr.write(cmd)

    def reset(self):
        """Reset the instrument to the factory default configuration."""
        cmd = f"*RST"
        self.instr.write(cmd)

    def save_setup(self, number):
        """Save the instrument setup in a settings buffer.

        Parameters
        ----------
        number : {1 - 9}
            Buffer number, 1 =< number =< 9.
        """
        cmd = f"*SAV {number}"
        self.instr.write(cmd)

    def set_status_byte_enable_register(self, value):
        """Enable bits in the status byte enable register.

        Parameters
        ----------
        value : int
            Decimal value of the enable register corresponding to the sum of binary
            weights of the bits to be enabled, e.g. to enable bits 1 and 3 only would
            require setting the value to 2^1 + 2^3 = 10. Must be in range 0 - 255.
        """
        if (value >= 0) & (value <= 255):
            self.instr.write(f"*SRE {value}")
        else:
            raise ValueError(
                f"Value: {value} is out of range. Must be in range 0-255."
            )

    def get_status_byte_enable_register(self):
        """Get the status byte enable register value.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self.instr.query("*SRE?"))

        return value

    def get_status_byte_register(self):
        """Get the status byte register value.

        Querying this register does not clear it.

        Returns
        -------
        value : int
            Register value.
        """
        value = int(self.instr.query("*STB?"))

        return value

    def trigger(self):
        """Generate a trigger.

        Only available when bus (software) trigger is selected.
        """
        self.instr.write("*TRG")

    def get_self_test_results(self):
        """Get the results of the instrument self-test.

        Returns
        -------
        result : list
            List of test results for the top board, bottom board, and fan.    
        """
        result = self.instr.query("*TST?").split(",")

        return result

    def wait(self):
        """Wait until processing all pending commands is complete."""
        self.instr.write("*WAI")

    # --- INITiate command ---

    def init_trigger(self):
        """Initialise the trigger system."""
        cmd = ":INIT"
        self.instr.write(cmd)

    # --- INSTrument commands ---

    def set_trigger_coupling_channels(self, channels):
        """Set trigger coupling channels.

        Only applicable to multi-channel models.

        Parameters
        ----------
        channels : 'ALL', 'NONE', or list containing 'CH1', 'CH2', 'CH3'
            Trigger coupling channels. If list, should contain at least two channels.
        """
        cmd = ":INST:COUP "
        if type(channels) is list:
            channels = channels.join(",")
        cmd = cmd + channels
        self.instr.write(cmd)

    def get_trigger_coupling_channels(self):
        """Get trigger coupling channels.

        Only applicable to multi-channel models.

        Returns
        -------
        channels : str or list
            If 'ALL' or 'NONE' that string is returned. Otherwise query returns a list
            where each element is a channel name and rating separated by a `:`.
        """
        channels = self.instr.query(":INST:COUP?").split(",")
        if len(channels) == 1:
            channels = channels[0]

        return channels

    def set_channel(self, channel):
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
        self.instr.write(f":INST CH{channel}")

    def get_channel(self):
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
        channel = int(self.instr.query(":INST:NSEL?"))

        return channel

    # --- LIC commands ---

    def install_options(self, options_licence):
        """Install options.

        Only applicable to DP831/DP832/DP821/DP811.

        Parameters
        ----------
        options_licence : str
            Unique 28-byte ASCII string only including English letters and numbers.
        """
        self.instr.write(f":LIC:SET {options_licence}")

    # --- MEASure commands ---

    # --- MEMory commands ---

    # --- MMEMory commands ---

    # --- MONItor commands ---

    # --- OUTPut commands ---

    # --- PRESet commands ---

    # --- RECAll commands ---

    # --- RECorder commands ---

    # --- SOURce commands ---

    # --- STATus commands ---

    # --- STORe commands ---

    # --- SYSTem commands ---

    # --- TIMEr commands ---

    # --- TRIGger commands ---
