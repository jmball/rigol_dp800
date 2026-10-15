# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel views sharing their parent supply's connection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .dp800 import DP800


class DP800Channel:
    """A fixed physical output using its parent supply's connection.

    Prefer supply.channels[channel] to obtain a stable channel object.
    All hardware settings and measurements perform VISA I/O. Each operation
    addresses this channel explicitly without changing selected_channel.
    Objects remain usable after reconnecting the parent and address its current
    instrument. Channel numbers are limited to 1 - 3; support for an individual
    channel is checked by the instrument, not this view.

    Parameters
    ----------
    supply : DP800 or virtual_dp800.DP800
        Parent driver. The channel never opens or closes its connection.
    channel : int
        One-based physical channel number.
    """

    def __init__(self, supply: DP800, channel: int) -> None:
        """Bind a physical channel to an existing supply.

        Parameters
        ----------
        supply : DP800 or VirtualDP800
            Parent driver whose connection and channel-specific operations are used.
        channel : int
            One-based physical channel number.
        """
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise TypeError("Channel must be an integer.")
        if not 1 <= channel <= 3:
            raise ValueError("Channel must be in the range 1 - 3.")
        self._supply = supply
        self._channel = channel

    @property
    def channel(self) -> int:
        """One-based physical channel number; reading it performs no I/O.

        Returns
        -------
        value : int
            One-based physical channel number.
        """
        return self._channel

    @property
    def voltage(self) -> float:
        """Configured voltage in volts; reading and assigning perform VISA I/O.

        Returns
        -------
        value : float
            Configured voltage in volts.
        """
        return self._supply.get_voltage(channel=self._channel)

    @voltage.setter
    def voltage(self, value: float | Literal["MIN", "MAX", "UP", "DOWN"]) -> None:
        """Set the configured channel voltage in volts.

        Each assignment uses the parent connection and explicitly addresses this
        channel.

        Parameters
        ----------
        value : float
            Configured voltage in volts.
        """
        self._supply.set_voltage(value, channel=self._channel)

    @property
    def current(self) -> float:
        """Configured current in amps; reading and assigning perform VISA I/O.

        Returns
        -------
        value : float
            Configured current in amps.
        """
        return self._supply.get_current(channel=self._channel)

    @current.setter
    def current(self, value: float | Literal["MIN", "MAX", "UP", "DOWN"]) -> None:
        """Set the configured channel current in amps.

        Each assignment uses the parent connection and explicitly addresses this
        channel.

        Parameters
        ----------
        value : float
            Configured current in amps.
        """
        self._supply.set_current(value, channel=self._channel)

    @property
    def output_enabled(self) -> bool:
        """Output enable state; reading and assigning perform VISA I/O.

        Returns
        -------
        value : bool
            Whether the channel output is enabled.
        """
        return self._supply.get_output_enable(channel=self._channel)

    @output_enabled.setter
    def output_enabled(self, enabled: bool) -> None:
        """Enable or disable the channel output.

        Each assignment uses the parent connection and explicitly addresses this
        channel.

        Parameters
        ----------
        enabled : bool
            Whether the channel output should be enabled.
        """
        self._supply.set_output_enable(enabled, channel=self._channel)

    @property
    def output_mode(self) -> str:
        """Query the channel's voltage/current regulation mode.

        Returns
        -------
        mode : str
            'CV' for constant voltage, 'CC' for constant current, or 'UR' for
            unregulated output. The virtual driver returns an empty string.
        """
        return self._supply.get_output_mode(channel=self._channel)

    @property
    def sense_enabled(self) -> bool:
        """Query remote sensing, where supported by the model and channel.

        Returns
        -------
        enabled : bool
            Whether remote sensing is enabled.
        """
        return self._supply.get_output_sense_enable(channel=self._channel)

    @sense_enabled.setter
    def sense_enabled(self, enabled: bool) -> None:
        """Set remote sensing, where supported by the model and channel.

        Parameters
        ----------
        enabled : bool
            Whether remote sensing should be enabled.
        """
        self._supply.set_output_sense_enable(enabled, channel=self._channel)

    @property
    def ocp_enabled(self) -> bool:
        """Query the overcurrent protection enable state.

        Returns
        -------
        enabled : bool
            Whether overcurrent protection is enabled.
        """
        return self._supply.get_ocp_enable(channel=self._channel)

    @ocp_enabled.setter
    def ocp_enabled(self, enabled: bool) -> None:
        """Enable or disable overcurrent protection.

        Parameters
        ----------
        enabled : bool
            Whether overcurrent protection should be enabled.
        """
        self._supply.set_ocp_enable(enabled, channel=self._channel)

    @property
    def ocp_value(self) -> float:
        """Query the overcurrent protection threshold in amps.

        Returns
        -------
        value : float
            Configured overcurrent protection threshold in amps.
        """
        return self._supply.get_ocp_value(channel=self._channel)

    @ocp_value.setter
    def ocp_value(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set the overcurrent protection threshold.

        Parameters
        ----------
        value : float or {'MIN', 'MAX'}
            Threshold in amps, or the instrument's minimum or maximum value.
        """
        self._supply.set_ocp_value(value, channel=self._channel)

    @property
    def ocp_tripped(self) -> bool:
        """Query whether overcurrent protection has tripped.

        Returns
        -------
        tripped : bool
            Whether the overcurrent protection alarm is active.
        """
        return self._supply.get_ocp(channel=self._channel)

    def clear_ocp_label(self) -> None:
        """Clear this channel's overcurrent protection alarm label."""
        self._supply.clear_ocp_label(channel=self._channel)

    @property
    def ovp_enabled(self) -> bool:
        """Query the overvoltage protection enable state.

        Returns
        -------
        enabled : bool
            Whether overvoltage protection is enabled.
        """
        return self._supply.get_ovp_enable(channel=self._channel)

    @ovp_enabled.setter
    def ovp_enabled(self, enabled: bool) -> None:
        """Enable or disable overvoltage protection.

        Parameters
        ----------
        enabled : bool
            Whether overvoltage protection should be enabled.
        """
        self._supply.set_ovp_enable(enabled, channel=self._channel)

    @property
    def ovp_value(self) -> float:
        """Query the overvoltage protection threshold in volts.

        Returns
        -------
        value : float
            Configured overvoltage protection threshold in volts.
        """
        return self._supply.get_ovp_value(channel=self._channel)

    @ovp_value.setter
    def ovp_value(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set the overvoltage protection threshold.

        Parameters
        ----------
        value : float or {'MIN', 'MAX'}
            Threshold in volts, or the instrument's minimum or maximum value.
        """
        self._supply.set_ovp_value(value, channel=self._channel)

    @property
    def ovp_tripped(self) -> bool:
        """Query whether overvoltage protection has tripped.

        Returns
        -------
        tripped : bool
            Whether the overvoltage protection alarm is active.
        """
        return self._supply.get_ovp(channel=self._channel)

    def clear_ovp_label(self) -> None:
        """Clear this channel's overvoltage protection alarm label."""
        self._supply.clear_ovp_label(channel=self._channel)

    @property
    def measured_voltage(self) -> float:
        """Actual voltage in volts; each access performs VISA I/O.

        Returns
        -------
        value : float
            Actual output voltage in volts.
        """
        return self._measure_scalar("VOLT")

    @property
    def measured_current(self) -> float:
        """Actual current in amps; each access performs VISA I/O.

        Returns
        -------
        value : float
            Actual output current in amps.
        """
        return self._measure_scalar("CURR")

    @property
    def measured_power(self) -> float:
        """Actual power in watts; each access performs VISA I/O.

        Returns
        -------
        value : float
            Actual output power in watts.
        """
        return self._measure_scalar("POWE")

    def measure(
        self, func: Literal["ALL", "CURR", "POWE", "VOLT"] | None = None
    ) -> str | list[str]:
        """Measure this channel, preserving the parent driver's response types.

        Parameters
        ----------
        func : {'ALL', 'CURR', 'POWE', 'VOLT'}, optional
            Quantity to measure. Omit for voltage, or use 'ALL' for voltage,
            current, and power in that order.

        Returns
        -------
        values : str or list of str
            Unconverted response strings from the parent driver. ALL returns
            voltage, current and power strings in that order.
        """
        return self._supply.measure(func, channel=self._channel)

    @property
    def voltage_step(self) -> float:
        """Voltage increment in volts.

        Returns
        -------
        value : float
            Voltage increment in volts.
        """
        return self._supply.get_voltage_step(channel=self._channel)

    @voltage_step.setter
    def voltage_step(self, value: float) -> None:
        """Set voltage increment in volts.

        Parameters
        ----------
        value : float
            Voltage increment in volts.
        """
        self._supply.set_voltage_step(value, channel=self._channel)

    @property
    def current_step(self) -> float:
        """Current increment in amps.

        Returns
        -------
        value : float
            Current increment in amps.
        """
        return self._supply.get_current_step(channel=self._channel)

    @current_step.setter
    def current_step(self, value: float) -> None:
        """Set current increment in amps.

        Parameters
        ----------
        value : float
            Current increment in amps.
        """
        self._supply.set_current_step(value, channel=self._channel)

    @property
    def tracking_enabled(self) -> bool:
        """Tracking state on supported channels.

        Returns
        -------
        value : bool
            Tracking state on supported channels.
        """
        return self._supply.get_output_track(channel=self._channel)

    @tracking_enabled.setter
    def tracking_enabled(self, value: bool) -> None:
        """Set tracking state on supported channels.

        Parameters
        ----------
        value : bool
            Tracking state on supported channels.
        """
        self._supply.set_output_track(value, channel=self._channel)

    @property
    def questionable_enable_register(self) -> int:
        """Channel questionable-status enable mask.

        Returns
        -------
        value : int
            Channel questionable-status enable mask.
        """
        return self._supply.get_channel_questionable_enable(channel=self._channel)

    @questionable_enable_register.setter
    def questionable_enable_register(self, value: int) -> None:
        """Set channel questionable-status enable mask.

        Parameters
        ----------
        value : int
            Channel questionable-status enable mask.
        """
        self._supply.set_channel_questionable_enable(value, channel=self._channel)

    @property
    def triggered_voltage(self) -> float:
        """Read the triggered voltage level.

        Returns
        -------
        value : float
            Configured triggered level in volts or amps.
        """
        return self._supply.get_source_trigger("VOLT", channel=self._channel)

    @triggered_voltage.setter
    def triggered_voltage(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set the triggered voltage level.

        Parameters
        ----------
        value : float or {"MIN", "MAX"}
            Triggered level in volts or amps, or a supported bound.
        """
        self._supply.set_source_trigger("VOLT", value, channel=self._channel)

    @property
    def triggered_current(self) -> float:
        """Read the triggered current level.

        Returns
        -------
        value : float
            Configured triggered level in volts or amps.
        """
        return self._supply.get_source_trigger("CURR", channel=self._channel)

    @triggered_current.setter
    def triggered_current(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set the triggered current level.

        Parameters
        ----------
        value : float or {"MIN", "MAX"}
            Triggered level in volts or amps, or a supported bound.
        """
        self._supply.set_source_trigger("CURR", value, channel=self._channel)

    def clear_ocp_circuit(self) -> None:
        """Clear the protection circuit and label, then re-enable this output."""
        self._supply.clear_ocp_circuit(channel=self._channel)

    def clear_ovp_circuit(self) -> None:
        """Clear the protection circuit and label, then re-enable this output."""
        self._supply.clear_ovp_circuit(channel=self._channel)

    def get_questionable_event(self) -> int:
        """Read and consume the channel questionable event register.

        Returns
        -------
        value : int
            Consumed event register.
        """
        return self._supply.get_channel_questionable_event(channel=self._channel)

    @property
    def questionable_condition(self) -> int:
        """Read the channel questionable condition register.

        Returns
        -------
        value : int
            Current condition bitmask.
        """
        return self._supply.get_channel_questionable_condition(self._channel)

    def _measure_scalar(self, func: Literal["CURR", "POWE", "VOLT"]) -> float:
        """Measure one quantity and convert its response to a float.

        Parameters
        ----------
        func : {'CURR', 'POWE', 'VOLT'}
            Quantity to measure: current ('CURR'), power ('POWE'), or voltage ('VOLT').

        Returns
        -------
        value : float
            Measured value converted to a float.
        """
        value = self.measure(func)
        if isinstance(value, list):
            raise ValueError(
                f"Expected one measurement for {func}, received {value!r}."
            )
        return float(value)
