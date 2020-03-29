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

    # --- INITiate command ---

    # --- INSTrument commands ---

    # --- LIC commands ---

    # --- MEASure commadns ---

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
