# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel views sharing their parent supply's connection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .dp800 import DP800
    from virtual_dp800.virtual_dp800 import DP800 as VirtualDP800


class DP800Channel:
    """A fixed physical output using its parent supply's connection.

    Prefer supply.channels[channel] to obtain a stable channel object.
    All hardware settings and measurements perform VISA I/O. Each operation
    addresses this channel explicitly without changing selected_channel.
    Objects remain usable after reconnecting the parent, provided the new
    instrument supports their channel number.

    Parameters
    ----------
    supply : DP800 or virtual_dp800.DP800
        Parent driver. The channel never opens or closes its connection.
    channel : int
        One-based physical channel number.
    """

    def __init__(self, supply: DP800 | VirtualDP800, channel: int) -> None:
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
        self._supply = supply
        self._channel = channel
        self._validate_channel()

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
        self._validate_channel()
        return self._supply.get_voltage(channel=self._channel)

    @voltage.setter
    def voltage(self, value: float) -> None:
        """Set the configured channel voltage in volts.

        Each assignment uses the parent connection and explicitly addresses this
        channel.

        Parameters
        ----------
        value : float
            Configured voltage in volts.
        """
        self._validate_channel()
        self._supply.set_voltage(value, channel=self._channel)

    @property
    def current(self) -> float:
        """Configured current in amps; reading and assigning perform VISA I/O.

        Returns
        -------
        value : float
            Configured current in amps.
        """
        self._validate_channel()
        return self._supply.get_current(channel=self._channel)

    @current.setter
    def current(self, value: float) -> None:
        """Set the configured channel current in amps.

        Each assignment uses the parent connection and explicitly addresses this
        channel.

        Parameters
        ----------
        value : float
            Configured current in amps.
        """
        self._validate_channel()
        self._supply.set_current(value, channel=self._channel)

    @property
    def output_enabled(self) -> bool:
        """Output enable state; reading and assigning perform VISA I/O.

        Returns
        -------
        value : bool
            Whether the channel output is enabled.
        """
        self._validate_channel()
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
        self._validate_channel()
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
        self._validate_channel()
        return self._supply.get_output_mode(channel=self._channel)

    @property
    def sense_enabled(self) -> bool:
        """Query remote sensing, where supported by the model and channel.

        Returns
        -------
        enabled : bool
            Whether remote sensing is enabled.
        """
        self._validate_channel()
        return self._supply.get_output_sense_enable(channel=self._channel)

    @sense_enabled.setter
    def sense_enabled(self, enabled: bool) -> None:
        """Set remote sensing, where supported by the model and channel.

        Parameters
        ----------
        enabled : bool
            Whether remote sensing should be enabled.
        """
        self._validate_channel()
        self._supply.set_output_sense_enable(enabled, channel=self._channel)

    @property
    def ocp_enabled(self) -> bool:
        """Query the overcurrent protection enable state.

        Returns
        -------
        enabled : bool
            Whether overcurrent protection is enabled.
        """
        self._validate_channel()
        return self._supply.get_ocp_enable(channel=self._channel)

    @ocp_enabled.setter
    def ocp_enabled(self, enabled: bool) -> None:
        """Enable or disable overcurrent protection.

        Parameters
        ----------
        enabled : bool
            Whether overcurrent protection should be enabled.
        """
        self._validate_channel()
        self._supply.set_ocp_enable(enabled, channel=self._channel)

    @property
    def ocp_value(self) -> float:
        """Query the overcurrent protection threshold in amps.

        Returns
        -------
        value : float
            Configured overcurrent protection threshold in amps.
        """
        self._validate_channel()
        return self._supply.get_ocp_value(channel=self._channel)

    @ocp_value.setter
    def ocp_value(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set the overcurrent protection threshold.

        Parameters
        ----------
        value : float or {'MIN', 'MAX'}
            Threshold in amps, or the instrument's minimum or maximum value.
        """
        self._validate_channel()
        self._supply.set_ocp_value(value, channel=self._channel)

    @property
    def ocp_tripped(self) -> bool:
        """Query whether overcurrent protection has tripped.

        Returns
        -------
        tripped : bool
            Whether the overcurrent protection alarm is active.
        """
        self._validate_channel()
        return self._supply.get_ocp(channel=self._channel)

    def clear_ocp_label(self) -> None:
        """Clear this channel's overcurrent protection alarm label."""
        self._validate_channel()
        self._supply.clear_ocp_label(channel=self._channel)

    @property
    def ovp_enabled(self) -> bool:
        """Query the overvoltage protection enable state.

        Returns
        -------
        enabled : bool
            Whether overvoltage protection is enabled.
        """
        self._validate_channel()
        return self._supply.get_ovp_enable(channel=self._channel)

    @ovp_enabled.setter
    def ovp_enabled(self, enabled: bool) -> None:
        """Enable or disable overvoltage protection.

        Parameters
        ----------
        enabled : bool
            Whether overvoltage protection should be enabled.
        """
        self._validate_channel()
        self._supply.set_ovp_enable(enabled, channel=self._channel)

    @property
    def ovp_value(self) -> float:
        """Query the overvoltage protection threshold in volts.

        Returns
        -------
        value : float
            Configured overvoltage protection threshold in volts.
        """
        self._validate_channel()
        return self._supply.get_ovp_value(channel=self._channel)

    @ovp_value.setter
    def ovp_value(self, value: float | Literal["MIN", "MAX"]) -> None:
        """Set the overvoltage protection threshold.

        Parameters
        ----------
        value : float or {'MIN', 'MAX'}
            Threshold in volts, or the instrument's minimum or maximum value.
        """
        self._validate_channel()
        self._supply.set_ovp_value(value, channel=self._channel)

    @property
    def ovp_tripped(self) -> bool:
        """Query whether overvoltage protection has tripped.

        Returns
        -------
        tripped : bool
            Whether the overvoltage protection alarm is active.
        """
        self._validate_channel()
        return self._supply.get_ovp(channel=self._channel)

    def clear_ovp_label(self) -> None:
        """Clear this channel's overvoltage protection alarm label."""
        self._validate_channel()
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
    ) -> str | list[str] | float:
        """Measure this channel, preserving the parent driver's response types.

        Parameters
        ----------
        func : {'ALL', 'CURR', 'POWE', 'VOLT'}, optional
            Quantity to measure. Omit for voltage, or use 'ALL' for voltage,
            current, and power in that order.

        Returns
        -------
        values : str or list of str or float
            Unconverted response from the parent. Hardware returns strings;
            the virtual driver's existing placeholder returns 0.0.
        """
        self._validate_channel()
        return self._supply.measure(func, channel=self._channel)

    def _validate_channel(self) -> None:
        """Check that this physical channel is available on the current supply.

        Reconnecting the parent can change its model while this object remains
        alive. Within a connection, the parent's channel count is cached.
        """
        if not 1 <= self._channel <= self._supply.channel_count:
            raise ValueError(
                f"Channel {self._channel} is not available on this supply."
            )

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
