# SPDX-License-Identifier: GPL-3.0-or-later

"""Real SCPI round trips, selected explicitly by the hardware CLI options.

These are interface/communication checks, not calibrated performance tests.
"""

import math

import pytest
import pyvisa

from dp800 import InstrumentError
from tests.api import READ_PROPERTIES

pytestmark = pytest.mark.hardware


@pytest.mark.parametrize("name", READ_PROPERTIES)
def test_read_properties(hardware, bench_config, name):
    if (
        name in {"selected_channel", "trigger_coupling_channels"}
        and len(bench_config.physical_channels) == 1
    ):
        pytest.skip("multi-channel command")
    value = getattr(hardware, name)
    if name == "identity":
        assert len(value) == 4 and value[1].strip() == bench_config.model
    elif name == "self_test_results":
        assert len(value) == 3
        assert all(item.strip().rsplit(":", 1)[-1].upper() == "PASS" for item in value)
    elif name == "temperature_test_result":
        assert isinstance(value, float) and math.isfinite(value)
    elif name in {"selected_channel", "delay_groups"}:
        assert isinstance(value, int) and value >= 1
    elif name in {
        "standard_event_enable_register",
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
        ("standard_event_enable_register", [0, 1, 255]),
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


def test_channel_selection_and_coupling(hardware, bench_config):
    if len(bench_config.physical_channels) == 1:
        pytest.skip("multi-channel commands")
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


def test_error_queue_is_consumed(hardware):
    # Raw writes deliberately avoid the automatic consuming check.
    hardware._instr.write(":DP800_TEST_INVALID_COMMAND")
    errors = hardware.get_errors()
    assert errors
    assert all(int(response.partition(",")[0]) != 0 for response in errors)
    assert hardware.get_errors() == []


def test_invalid_write_raises_raw_instrument_error(hardware):
    with pytest.raises(InstrumentError) as raised:
        hardware._write(":SOUR4:VOLT 1")
    assert int(str(raised.value).partition(",")[0]) != 0
    assert hardware.get_errors() == []


def test_invalid_query_timeout_diagnoses_instrument_error(hardware):
    # This deliberately verifies firmware behavior rather than assuming it.
    with pytest.raises(InstrumentError) as raised:
        hardware._query(":SOUR4:VOLT?")
    assert isinstance(raised.value.__cause__, pyvisa.errors.VisaIOError)
    assert (
        raised.value.__cause__.error_code == pyvisa.constants.StatusCode.error_timeout
    )
    assert hardware.get_errors() == []
