# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel and parent API round trips for each requested physical channel."""

import math

import pytest

pytestmark = pytest.mark.hardware


@pytest.fixture(params=[1, 2, 3], ids=lambda number: f"CH{number}")
def channel_number(request, bench_config):
    if request.param not in bench_config.channels:
        pytest.skip("channel absent from model or excluded by --hardware-channels")
    return request.param


@pytest.fixture
def channel(hardware, channel_number):
    return hardware.channels[channel_number]


def select_channel(supply, config, number):
    if len(config.physical_channels) > 1:
        supply.selected_channel = number


def test_setpoints_and_apply(hardware, channel, bench_config):
    number = channel.channel
    original_voltage, original_current = channel.voltage, channel.current
    selected = (
        hardware.selected_channel if len(bench_config.physical_channels) > 1 else None
    )
    voltage, current = bench_config.channel_voltage(number), bench_config.current
    try:
        channel.voltage, channel.current = voltage, current
        assert channel.voltage == pytest.approx(voltage, abs=0.01)
        assert channel.current == pytest.approx(current, abs=0.01)
        select_channel(hardware, bench_config, number)
        for addressed in (number, None):
            hardware.set_voltage(voltage, channel=addressed)
            hardware.set_current(current, channel=addressed)
            assert hardware.get_voltage(addressed) == pytest.approx(voltage, abs=0.01)
            assert hardware.get_current(addressed) == pytest.approx(current, abs=0.01)
            hardware.set_apply(addressed, voltage, current)
            result = hardware.get_apply(addressed)
            assert isinstance(result, tuple) and len(result) == 4
            assert result[0] == f"CH{number}"
            assert result[2:] == pytest.approx((voltage, current), abs=0.01)
        for function, value in (("VOLT", voltage), ("CURR", current)):
            assert hardware.get_apply(number, function) == pytest.approx(
                value, abs=0.01
            )
        hardware.set_apply(number, voltage)
        assert channel.voltage == pytest.approx(voltage, abs=0.01)
    finally:
        channel.voltage, channel.current = original_voltage, original_current
        if selected is not None:
            hardware.selected_channel = selected


@pytest.mark.parametrize("protection", ["ocp", "ovp"])
def test_protection_settings_and_alarm_labels(
    hardware, channel, bench_config, protection
):
    value_name, enable_name = f"{protection}_value", f"{protection}_enabled"
    original_value, original_enabled = getattr(channel, value_name), getattr(
        channel, enable_name
    )
    selected = (
        hardware.selected_channel if len(bench_config.physical_channels) > 1 else None
    )
    # Reuse the existing valid threshold instead of imposing model-specific ranges.
    try:
        select_channel(hardware, bench_config, channel.channel)
        setattr(channel, value_name, original_value)
        assert getattr(channel, value_name) == pytest.approx(original_value)
        for enabled in (True, False):
            setattr(channel, enable_name, enabled)
            assert getattr(channel, enable_name) is enabled
            for addressed in (channel.channel, None):
                getattr(hardware, f"set_{protection}_enable")(
                    enabled, channel=addressed
                )
                assert (
                    getattr(hardware, f"get_{protection}_enable")(addressed) is enabled
                )
                getattr(hardware, f"set_{protection}_value")(
                    original_value, channel=addressed
                )
                assert getattr(hardware, f"get_{protection}_value")(
                    addressed
                ) == pytest.approx(original_value)
        getattr(channel, f"clear_{protection}_label")()
        assert getattr(channel, f"{protection}_tripped") is False
        for addressed in (channel.channel, None):
            getattr(hardware, f"clear_{protection}_label")(channel=addressed)
            assert getattr(hardware, f"get_{protection}")(addressed) is False
    finally:
        setattr(channel, value_name, original_value)
        setattr(channel, enable_name, original_enabled)
        if selected is not None:
            hardware.selected_channel = selected


def test_remote_sensing(hardware, channel, bench_config):
    if channel.channel not in bench_config.sense_channels:
        pytest.skip("remote sensing is unsupported on this model/channel")
    original = channel.sense_enabled
    selected = (
        hardware.selected_channel if len(bench_config.physical_channels) > 1 else None
    )
    try:
        select_channel(hardware, bench_config, channel.channel)
        for enabled in (True, False):
            channel.sense_enabled = enabled
            assert channel.sense_enabled is enabled
            for addressed in (channel.channel, None):
                hardware.set_output_sense_enable(enabled, channel=addressed)
                assert hardware.get_output_sense_enable(addressed) is enabled
    finally:
        channel.sense_enabled = original
        if selected is not None:
            hardware.selected_channel = selected


def test_output_off_and_measurements(hardware, channel, bench_config):
    selected = (
        hardware.selected_channel if len(bench_config.physical_channels) > 1 else None
    )
    try:
        select_channel(hardware, bench_config, channel.channel)
        channel.output_enabled = False
        assert channel.output_enabled is False
        assert channel.output_mode in {"CV", "CC", "UR"}
        for name in ("measured_voltage", "measured_current", "measured_power"):
            assert math.isfinite(getattr(channel, name))
        for function in (None, "VOLT", "CURR", "POWE", "ALL"):
            values = [
                channel.measure(function),
                hardware.measure(function),
                hardware.measure(function, channel.channel),
            ]
            for result in values:
                if function == "ALL":
                    assert isinstance(result, list) and len(result) == 3
                    assert all(math.isfinite(float(value)) for value in result)
                else:
                    assert isinstance(result, str) and math.isfinite(float(result))
        for addressed in (channel.channel, None):
            hardware.set_output_enable(False, channel=addressed)
            assert hardware.get_output_enable(addressed) is False
            assert hardware.get_output_mode(addressed) in {"CV", "CC", "UR"}
    finally:
        if selected is not None:
            hardware.selected_channel = selected


def test_output_on(hardware, channel, bench_config):
    if not bench_config.allow_output:
        pytest.skip("output activation requires --hardware-allow-output")
    voltage, current = channel.voltage, channel.current
    sense = (
        channel.sense_enabled
        if channel.channel in bench_config.sense_channels
        else None
    )
    try:
        if sense is not None:
            channel.sense_enabled = False
        channel.voltage = bench_config.channel_voltage(channel.channel)
        channel.current = bench_config.current
        channel.output_enabled = True
        assert channel.output_enabled is True
        assert math.isfinite(channel.measured_voltage)
        assert math.isfinite(channel.measured_current)
        assert math.isfinite(channel.measured_power)
    finally:
        channel.output_enabled = False
        channel.voltage, channel.current = voltage, current
        if sense is not None:
            channel.sense_enabled = sense
