# SPDX-License-Identifier: GPL-3.0-or-later

"""Full guide-family command contracts, selectors, blocks and string handling."""

import pytest

from dp800 import DP800
from dp800.dp800 import _block, _enabled, _number
from tests.extended_api import METHODS, PROPERTIES


@pytest.fixture
def connected(fake_visa):
    driver, resource, manager = fake_visa
    driver.connect("fake", resource_manager=manager)
    return driver, resource


@pytest.mark.parametrize("name", PROPERTIES)
def test_property_query_contract(connected, name):
    driver, resource = connected
    command, raw, expected, _, _ = PROPERTIES[name]
    resource.responses[command] = raw
    assert getattr(driver, name) == expected
    assert resource.commands[-1] == command
    assert resource.io_events[-1] == ":SYST:ERR?"
    driver.disconnect()
    with pytest.raises(RuntimeError, match="not connected"):
        getattr(driver, name)


@pytest.mark.parametrize("name", [name for name, case in PROPERTIES.items() if case[4]])
def test_property_assignment_contract(connected, name):
    driver, resource = connected
    _, _, _, value, command = PROPERTIES[name]
    setattr(driver, name, value)
    assert resource.commands[-1] == command
    assert resource.io_events[-1] == ":SYST:ERR?"
    driver.disconnect()
    with pytest.raises(RuntimeError, match="not connected"):
        setattr(driver, name, value)


@pytest.mark.parametrize("case", METHODS, ids=lambda case: case[0] + "-" + case[3])
def test_method_contract(connected, case):
    driver, resource = connected
    name, args, kwargs, command, raw, expected = case
    if raw is not None:
        resource.responses[command] = raw
    assert getattr(driver, name)(*args, **kwargs) == expected
    assert resource.commands[-1] == command
    assert resource.io_events[-1] == ":SYST:ERR?"
    driver.disconnect()
    with pytest.raises(RuntimeError, match="not connected"):
        getattr(driver, name)(*args, **kwargs)


@pytest.mark.parametrize("quantity", ["ocp", "ovp"])
@pytest.mark.parametrize("channel", [None, 2])
@pytest.mark.parametrize("limit", ["MIN", "MAX"])
def test_protection_bound_queries(connected, quantity, channel, limit):
    driver, resource = connected
    command = f":OUTP:{quantity.upper()}:VAL?" + (
        f" CH{channel},{limit}" if channel else f" {limit}"
    )
    resource.responses[command] = "1.500"
    assert getattr(driver, f"get_{quantity}_value")(channel, limit=limit) == 1.5
    assert resource.commands[-1] == command


@pytest.mark.parametrize("quantity,code", [("voltage", "VOLT"), ("current", "CURR")])
def test_step_default_query(connected, quantity, code):
    driver, resource = connected
    resource.responses[f":SOUR2:{code}:STEP? DEF"] = "0.01"
    assert getattr(driver, f"get_{quantity}_step")(2, default=True) == 0.01


@pytest.mark.parametrize("setting", ["current", "voltage", "ocp", "ovp"])
def test_preset_bound_query(connected, setting):
    driver, resource = connected
    code = {"current": "CURR", "voltage": "VOLT"}.get(setting, setting.upper())
    raw = "ON,1.5" if setting in ("ocp", "ovp") else "1.5"
    resource.responses[f":PRES:USER2:SET:{code}? MAX"] = raw
    assert getattr(driver, f"get_preset_{setting}")(2, limit="MAX") == (
        (True, 1.5) if "," in raw else 1.5
    )


@pytest.mark.parametrize("raw", ["#", "#0", "#xabc", "#912", "#12x", "#12abc"])
def test_malformed_block_is_rejected(raw):
    with pytest.raises(ValueError):
        _block(raw)


@pytest.mark.parametrize(
    "raw,expected", [("1.5V", 1.5), ("-2.5E-3A", -0.0025), (" 3.0 ", 3.0)]
)
def test_numeric_units(raw, expected):
    assert _number(raw) == expected


@pytest.mark.parametrize("raw", ["unknown", "NONE", "2"])
def test_unexpected_boolean_does_not_silently_become_false(raw):
    with pytest.raises(ValueError):
        _enabled(raw)


@pytest.mark.parametrize(
    "operation",
    [
        lambda d: d.set_display_text("x\n*RST"),
        lambda d: d.set_display_text("x", y=2),
        lambda d: d.set_display_text("x" * 46),
        lambda d: d.set_key_lock("CH1;*RST", True),
        lambda d: d.save_file("RSF", "D:\\file.RTF"),
        lambda d: d.set_apply(current=0.1),
        lambda d: d.set_apply(),
    ],
)
def test_invalid_configuration_sends_no_command(connected, operation):
    driver, resource = connected
    before = list(resource.io_events)
    with pytest.raises(ValueError):
        operation(driver)
    assert resource.io_events == before


@pytest.mark.parametrize(
    "name,raw,command,expected",
    [
        ("questionable_condition", "9", ":STAT:QUES:INST:ISUM2:COND?", 9),
        ("questionable_enable_register", "8", ":STAT:QUES:INST:ISUM2:ENAB?", 8),
        ("triggered_voltage", "2.0V", ":SOUR2:VOLT:TRIG?", 2.0),
        ("triggered_current", "0.2A", ":SOUR2:CURR:TRIG?", 0.2),
        ("voltage_step", "0.01", ":SOUR2:VOLT:STEP?", 0.01),
        ("current_step", "0.001", ":SOUR2:CURR:STEP?", 0.001),
        ("tracking_enabled", "ON", ":OUTP:TRAC? CH2", True),
    ],
)
def test_channel_extension_queries(connected, name, raw, command, expected):
    driver, resource = connected
    resource.responses[command] = raw
    assert getattr(driver.channels[2], name) == expected
    assert resource.commands[-1] == command


@pytest.mark.parametrize(
    "name,value,command",
    [
        ("questionable_enable_register", 8, ":STAT:QUES:INST:ISUM2:ENAB 8"),
        ("triggered_voltage", 2.0, ":SOUR2:VOLT:TRIG 2.0"),
        ("triggered_current", 0.2, ":SOUR2:CURR:TRIG 0.2"),
        ("voltage_step", 0.01, ":SOUR2:VOLT:STEP 0.01"),
        ("current_step", 0.001, ":SOUR2:CURR:STEP 0.001"),
        ("tracking_enabled", True, ":OUTP:TRAC CH2,ON"),
    ],
)
def test_channel_extension_assignments(connected, name, value, command):
    driver, resource = connected
    setattr(driver.channels[2], name, value)
    assert resource.commands[-1] == command


def test_channel_event_read_consumes_the_instrument_event(connected):
    driver, resource = connected
    resource.responses[":STAT:QUES:INST:ISUM2:EVEN?"] = "8"
    assert driver.channels[2].get_questionable_event() == 8
    assert resource.commands[-1] == ":STAT:QUES:INST:ISUM2:EVEN?"


@pytest.mark.parametrize("line,suffix", [(None, " ,MAX"), (2, " D2,MAX")])
def test_digital_output_condition_bound_selector(connected, line, suffix):
    driver, resource = connected
    resource.responses[":TRIG:OUT:COND?" + suffix] = ">V,30.000"
    assert driver.get_trigger_output_condition(line, limit="MAX") == (">V", 30.0)


def test_apply_can_select_without_changing_setpoints(connected):
    driver, resource = connected
    driver.set_apply(channel=2)
    assert resource.commands[-1] == ":APPL CH2"
