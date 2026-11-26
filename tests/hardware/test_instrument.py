# SPDX-License-Identifier: GPL-3.0-or-later

"""Real SCPI round trips, selected explicitly by the hardware CLI options.

These are interface/communication checks, not calibrated performance tests.
"""

import math

import pytest

from dp800 import InstrumentError

pytestmark = pytest.mark.hardware


def test_available_channels(hardware, bench_config):
    assert hardware.available_channels == bench_config.physical_channels


# These reads are suitable for a connected instrument without changing its state.
READ_ONLY_PROPERTIES = (
    "standard_event_enable_register",
    "status_byte_enable_register",
    "status_byte_register",
    "power_on_status_clear_bit",
    "identity",
    "option_installation_status",
    "self_test_results",
    "temperature_test_result",
    "delay_end_state",
    "delay_groups",
    pytest.param(
        "trigger_coupling_channels", marks=pytest.mark.supported_on("multi_channel")
    ),
    pytest.param("selected_channel", marks=pytest.mark.supported_on("multi_channel")),
    "keylock_enabled",
)


@pytest.mark.parametrize("name", READ_ONLY_PROPERTIES)
def test_read_properties(hardware, bench_config, name):
    value = getattr(hardware, name)
    if name == "identity":
        assert isinstance(value, str)
        fields = value.split(",")
        assert len(fields) == 4 and fields[1].strip() == bench_config.model
    elif name == "self_test_results":
        assert len(value) == 3
        assert all(item.strip().rsplit(":", 1)[-1].upper() == "PASS" for item in value)
    elif name == "temperature_test_result":
        assert isinstance(value, float) and math.isfinite(value)
    elif name in {"selected_channel", "delay_groups"}:
        assert isinstance(value, int) and value >= 1
    elif name == "standard_event_enable_register":
        assert isinstance(value, int) and value >= 0 and value & ~0xBD == 0
    elif name in {
        "status_byte_enable_register",
        "status_byte_register",
    }:
        assert isinstance(value, int) and 0 <= value <= 255
    elif name == "power_on_status_clear_bit":
        assert value in (0, 1)
    elif name == "keylock_enabled":
        assert isinstance(value, bool)
    elif name == "delay_end_state":
        assert value in {"ON", "OFF", "LAST"}
    elif name == "trigger_coupling_channels":
        assert value in ("ALL", "NONE") or isinstance(value, list)
    else:
        assert isinstance(value, str) and value
    assert hardware.get_errors() == []


@pytest.mark.parametrize(
    "name,values",
    [
        ("standard_event_enable_register", [0, 1, 20, 189]),
        # Bit 6 is reserved in SRE, so don't expect an all-bits value to round-trip.
        ("status_byte_enable_register", [0, 32]),
        ("power_on_status_clear_bit", [0, 1]),
        ("delay_groups", [1, 2]),
        ("delay_end_state", ["OFF", "LAST", "ON"]),
        ("keylock_enabled", [True, False]),
    ],
)
def test_property_round_trips(hardware, name, values):
    original = getattr(hardware, name)
    try:
        for value in values:
            setattr(hardware, name, value)
            assert getattr(hardware, name) == value
    finally:
        setattr(hardware, name, original)


@pytest.mark.supported_on("multi_channel")
def test_channel_selection_and_coupling(hardware, bench_config):
    selected, coupling = hardware.selected_channel, hardware.trigger_coupling_channels
    try:
        for number in bench_config.channels:
            hardware.selected_channel = number
            assert hardware.selected_channel == number
        for value in ("ALL", "NONE"):
            hardware.trigger_coupling_channels = value
            assert hardware.trigger_coupling_channels == value
        numbers = bench_config.physical_channels[:2]
        hardware.trigger_coupling_channels = [f"CH{number}" for number in numbers]
        result = hardware.trigger_coupling_channels
        assert isinstance(result, list)
        assert [item.split(":")[0] for item in result] == [
            f"CH{number}" for number in numbers
        ]
    finally:
        hardware.selected_channel = selected
        hardware.trigger_coupling_channels = (
            [item.split(":")[0] for item in coupling]
            if isinstance(coupling, list)
            else coupling
        )


def test_delay_cycles(hardware):
    original = hardware.get_delay_cycles()
    try:
        hardware.set_delay_cycles("N", 2)
        assert hardware.get_delay_cycles() == ("N", 2)
        hardware.set_delay_cycles("I")
        assert hardware.get_delay_cycles() == "I"
        hardware.set_delay_cycles("N")
        assert hardware.get_delay_cycles() == ("N", 1)
    finally:
        (
            hardware.set_delay_cycles(*original)
            if isinstance(original, tuple)
            else hardware.set_delay_cycles(original)
        )


def test_common_commands_and_modes(hardware):
    hardware.set_remote()
    hardware.set_local()
    hardware.clear_event_registers()
    assert hardware.get_standard_event_register() == 0
    hardware.set_opc()
    hardware.wait()
    assert hardware.get_opc() == 1
    assert hardware.get_standard_event_register() & 1
    assert hardware.get_standard_event_register() == 0


def test_rejected_setting_raises_and_consumes_instrument_error(hardware):
    # The guide's brightness range is 1-100. An out-of-range display setting
    # provokes a device error through the public API without affecting outputs.
    original = hardware.brightness
    try:
        with pytest.raises(InstrumentError) as raised:
            hardware.brightness = 101
        responses = str(raised.value).split("\n")
        assert all(int(response.partition(",")[0]) != 0 for response in responses)
        # The automatic check consumed every queued entry.
        assert hardware.get_errors() == []
    finally:
        hardware.brightness = original


def test_invalid_channel_is_rejected_without_disrupting_communication(
    hardware, bench_config
):
    invalid = max(bench_config.physical_channels) + 1
    with pytest.raises(ValueError, match="Channel"):
        hardware.get_voltage(channel=invalid)
    with pytest.raises(ValueError, match="Channel"):
        hardware.set_voltage(1.0, channel=invalid)
    assert hardware.identity.split(",")[1].strip().upper() == bench_config.model
    assert hardware.get_errors() == []


# Guide range selectors and the rated range each reports, per single-channel model.
RANGES = {
    "DP811": {"LOW": "20V/10A", "HIGH": "40V/5A", "P20V": "20V/10A", "P40V": "40V/5A"},
    "DP813": {"LOW": "8V/20A", "HIGH": "20V/10A", "P8V": "8V/20A", "P20V": "20V/10A"},
}


@pytest.mark.supported_on("single_channel")
def test_output_range(hardware, bench_config):
    ranges = RANGES[bench_config.base_model]
    original = hardware.output_range
    try:
        for selector, rating in ranges.items():
            hardware.output_range = selector
            assert hardware.output_range == rating
    finally:
        hardware.output_range = "LOW" if original == ranges["LOW"] else "HIGH"
    assert hardware.output_range == original


@pytest.mark.supported_on("single_channel")
def test_questionable_condition(hardware):
    assert hardware.questionable_condition >= 0
