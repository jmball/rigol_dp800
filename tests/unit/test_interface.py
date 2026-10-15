# SPDX-License-Identifier: GPL-3.0-or-later

"""Parameterized command contracts and full public API coverage inventory."""

import pytest

from dp800 import DP800, DP800Channel
from tests.extended_api import METHODS, PROPERTIES
from tests.api import (
    ACTIONS,
    CHANNEL_MEMBERS,
    CHANNEL_READS,
    CHANNEL_WRITES,
    READ_PROPERTIES,
    SPECIAL_API,
    WRITE_PROPERTIES,
)


@pytest.fixture
def connected(fake_visa):
    driver, resource, manager = fake_visa
    driver.connect("TCPIP::example::INSTR", resource_manager=manager)
    return driver, resource


@pytest.mark.parametrize("name", READ_PROPERTIES)
def test_property_reads(connected, name):
    driver, resource = connected
    command, response, expected = READ_PROPERTIES[name]
    resource.responses[command] = response
    assert getattr(driver, name) == expected
    assert getattr(driver, name) == expected
    assert resource.commands[-2:] == [command, command]
    failure = OSError("query failed")
    resource.query_error = failure
    with pytest.raises(OSError) as raised:
        getattr(driver, name)
    assert raised.value is failure
    resource.query_error = None
    driver.disconnect()
    with pytest.raises(RuntimeError, match="not connected"):
        getattr(driver, name)


@pytest.mark.parametrize("name", WRITE_PROPERTIES)
def test_property_assignments(connected, name):
    driver, resource = connected
    value, command = WRITE_PROPERTIES[name]
    setattr(driver, name, value)
    assert resource.commands[-1] == command
    failure = OSError("write failed")
    resource.write_errors[command] = failure
    with pytest.raises(OSError) as raised:
        setattr(driver, name, value)
    assert raised.value is failure
    resource.write_errors.clear()
    driver.disconnect()
    with pytest.raises(RuntimeError, match="not connected"):
        setattr(driver, name, value)


@pytest.mark.parametrize(
    "name,response,expected",
    [
        ("keylock_enabled", "OFF", False),
        ("trigger_coupling_channels", "ALL", "ALL"),
        ("trigger_coupling_channels", "NONE", "NONE"),
    ],
)
def test_alternative_property_responses(connected, name, response, expected):
    driver, resource = connected
    command = READ_PROPERTIES[name][0]
    resource.responses[command] = response
    assert getattr(driver, name) == expected


@pytest.mark.parametrize(
    "name,value,command",
    [
        ("delay_end_state", "ON", ":DELAY:ENDS ON"),
        ("delay_end_state", "OFF", ":DELAY:ENDS OFF"),
        ("keylock_enabled", False, ":SYST:KLOC:STAT OFF"),
        ("trigger_coupling_channels", "ALL", ":INST:COUP ALL"),
        ("trigger_coupling_channels", "NONE", ":INST:COUP NONE"),
    ],
)
def test_alternative_property_assignments(connected, name, value, command):
    driver, resource = connected
    setattr(driver, name, value)
    assert resource.commands[-1] == command


@pytest.mark.parametrize(
    "channel", [None, 2], ids=["selected-channel", "explicit-channel"]
)
@pytest.mark.parametrize("name", CHANNEL_READS)
def test_channel_getters(connected, name, channel):
    driver, resource = connected
    command, response, expected = CHANNEL_READS[name]
    if "{channel}" in command:
        command = (
            command.format(channel=channel)
            if channel is not None
            else command.replace(":SOUR{channel}", "")
        )
    elif channel is not None:
        command += f" CH{channel}"
    resource.responses[command] = response
    assert getattr(driver, name)(channel=channel) == expected
    assert resource.commands[-1] == command


@pytest.mark.parametrize(
    "channel", [None, 2], ids=["selected-channel", "explicit-channel"]
)
@pytest.mark.parametrize("name", CHANNEL_WRITES)
def test_channel_setters(connected, name, channel):
    driver, resource = connected
    value, implicit, explicit = CHANNEL_WRITES[name]
    getattr(driver, name)(value, channel=channel)
    assert resource.commands[-1] == (implicit if channel is None else explicit)


@pytest.mark.parametrize("name", ACTIONS)
def test_actions(connected, name):
    driver, resource = connected
    args, command = ACTIONS[name]
    getattr(driver, name)(*args)
    assert resource.commands[-1] == command


@pytest.mark.parametrize("name", ["clear_ocp_label", "clear_ovp_label"])
@pytest.mark.parametrize("channel", [None, 2])
def test_alarm_clearing(connected, name, channel):
    driver, resource = connected
    getattr(driver, name)(channel=channel)
    command = ":OUTP:" + ("OCP" if name == "clear_ocp_label" else "OVP") + ":CLEAR"
    if channel is not None:
        command += f" CH{channel}"
    assert resource.commands[-1] == command


@pytest.mark.parametrize("channel", [None, 2])
@pytest.mark.parametrize(
    "func,response,expected",
    [
        (None, "1.2", "1.2"),
        ("VOLT", "1.2", "1.2"),
        ("CURR", "0.1", "0.1"),
        ("POWE", "0.12", "0.12"),
        ("ALL", "1.2,0.1,0.12", ["1.2", "0.1", "0.12"]),
    ],
)
def test_measurements(connected, channel, func, response, expected):
    driver, resource = connected
    command = (
        ":MEAS"
        + (f":{func}" if func else "")
        + "?"
        + (f" CH{channel}" if channel else "")
    )
    resource.responses[command] = response
    assert driver.measure(func, channel=channel) == expected
    assert resource.commands[-1] == command


@pytest.mark.parametrize(
    "finite,cycles,response,expected,command",
    [
        ("N", 3, "N,3", ("N", 3), ":DELAY:CYCLE N,3"),
        ("N", None, "N,1", ("N", 1), ":DELAY:CYCLE N"),
        ("I", None, "I", "I", ":DELAY:CYCLE I"),
    ],
)
def test_delay_cycles(connected, finite, cycles, response, expected, command):
    driver, resource = connected
    driver.set_delay_cycles(finite, cycles)
    assert resource.commands[-1] == command
    resource.responses[":DELAY:CYCLE?"] = response
    assert driver.get_delay_cycles() == expected


@pytest.mark.parametrize("channel", [None, 2])
@pytest.mark.parametrize("current", [None, 0.1])
def test_apply_settings(connected, channel, current):
    driver, resource = connected
    driver.set_apply(channel=channel, voltage=1.2, current=current)
    command = (
        ":APPL "
        + (f"CH{channel}," if channel else "")
        + "1.2"
        + (",0.1" if current is not None else "")
    )
    assert resource.commands[-1] == command


@pytest.mark.parametrize("channel", [None, 2])
def test_apply_full_response(connected, channel):
    driver, resource = connected
    command = ":APPL?" + (f" CH{channel}" if channel else "")
    resource.responses[command] = "CH2,30V/3A,1.2,0.1"
    assert driver.get_apply(channel) == ("CH2", "30V/3A", 1.2, 0.1)


@pytest.mark.parametrize("func", ["VOLT", "CURR"])
def test_apply_function_response(connected, func):
    driver, resource = connected
    resource.responses[f":APPL? CH2,{func}"] = "1.2"
    assert driver.get_apply(2, func) == 1.2
    resource.responses[f":APPL?,{func}"] = "1.2"
    with pytest.raises(ValueError, match="Specify a channel"):
        driver.get_apply(function=func)


def test_public_interface_has_explicit_test_cases():
    covered = (
        set(READ_PROPERTIES)
        | set(WRITE_PROPERTIES)
        | set(CHANNEL_READS)
        | set(CHANNEL_WRITES)
        | set(ACTIONS)
        | SPECIAL_API
        | {"clear_ocp_label", "clear_ovp_label"}
    )
    members = {
        name
        for name, member in vars(DP800).items()
        if not name.startswith("_")
        and (callable(member) or isinstance(member, property))
    }
    covered |= set(PROPERTIES) | {case[0] for case in METHODS}
    assert members == covered
    channel_members = {
        name
        for name, member in vars(DP800Channel).items()
        if not name.startswith("_")
        and (callable(member) or isinstance(member, property))
    }
    assert channel_members == CHANNEL_MEMBERS
