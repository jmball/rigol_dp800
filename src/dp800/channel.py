# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel views sharing their parent supply's connection."""

from typing import Literal, Protocol


class _ChannelSupply(Protocol):
    """Operations needed by a channel, implemented by both drivers."""

    @property
    def channel_count(self) -> int: ...

    def get_voltage(self, channel: int | None = None) -> float: ...

    def set_voltage(self, voltage: float, channel: int | None = None) -> None: ...

    def get_current(self, channel: int | None = None) -> float: ...

    def set_current(self, current: float, channel: int | None = None) -> None: ...

    def get_output_enable(self, channel: int | None = None) -> bool: ...

    def set_output_enable(self, enable: bool, channel: int | None = None) -> None: ...

    def measure(
        self,
        func: Literal["ALL", "CURR", "POWE", "VOLT"] | None = None,
        channel: int | None = None,
    ) -> str | list[str] | float: ...


class DP800Channel:
    """A fixed physical output using its parent supply's connection.

    Parameters
    ----------
    supply : dp800 or virtual_dp800.dp800
        Parent driver. The channel never opens or closes its connection.
    channel : int
        One-based physical channel number.

    Notes
    -----
    Prefer supply.channels[channel] to obtain a stable channel object.
    All hardware settings and measurements perform VISA I/O. Each operation
    addresses this channel explicitly without changing selected_channel.
    Objects remain usable after reconnecting the parent, provided the new
    instrument supports their channel number.
    """

    def __init__(self, supply: _ChannelSupply, channel: int) -> None:
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise TypeError("Channel must be an integer.")
        self._supply = supply
        self._channel = channel
        self._validate_channel()

    def _validate_channel(self) -> None:
        if not 1 <= self._channel <= self._supply.channel_count:
            raise ValueError(
                f"Channel {self._channel} is not available on this supply."
            )

    @property
    def channel(self) -> int:
        """One-based physical channel number; reading it performs no I/O."""
        return self._channel

    @property
    def voltage(self) -> float:
        """Configured voltage in volts; reading and assigning perform VISA I/O."""
        self._validate_channel()
        return self._supply.get_voltage(channel=self._channel)

    @voltage.setter
    def voltage(self, value: float) -> None:
        self._validate_channel()
        self._supply.set_voltage(value, channel=self._channel)

    @property
    def current(self) -> float:
        """Configured current in amps; reading and assigning perform VISA I/O."""
        self._validate_channel()
        return self._supply.get_current(channel=self._channel)

    @current.setter
    def current(self, value: float) -> None:
        self._validate_channel()
        self._supply.set_current(value, channel=self._channel)

    @property
    def output_enabled(self) -> bool:
        """Output enable state; reading and assigning perform VISA I/O."""
        self._validate_channel()
        return self._supply.get_output_enable(channel=self._channel)

    @output_enabled.setter
    def output_enabled(self, enabled: bool) -> None:
        self._validate_channel()
        self._supply.set_output_enable(enabled, channel=self._channel)

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

    def _measure_scalar(self, func: Literal["CURR", "POWE", "VOLT"]) -> float:
        value = self.measure(func)
        if isinstance(value, list):
            raise ValueError(
                f"Expected one measurement for {func}, received {value!r}."
            )
        return float(value)

    @property
    def measured_voltage(self) -> float:
        """Actual voltage in volts; each access performs VISA I/O."""
        return self._measure_scalar("VOLT")

    @property
    def measured_current(self) -> float:
        """Actual current in amps; each access performs VISA I/O."""
        return self._measure_scalar("CURR")

    @property
    def measured_power(self) -> float:
        """Actual power in watts; each access performs VISA I/O."""
        return self._measure_scalar("POWE")
