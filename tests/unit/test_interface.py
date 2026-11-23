# SPDX-License-Identifier: GPL-3.0-or-later

"""Focused command, response, and addressing contracts for the core API."""

import pytest

# Literal SCPI cases live beside the tests that exercise them.
READ_PROPERTIES = {
    "standard_event_enable_register": ("*ESE?", "20", 20),
    "status_byte_enable_register": ("*SRE?", "32", 32),
    "status_byte_register": ("*STB?", "16", 16),
    "power_on_status_clear_bit": ("*PSC?", "1", 1),
    "identity": (
        "*IDN?",
        "RIGOL, DP832, serial, version",
        "RIGOL, DP832, serial, version",
    ),
    "option_installation_status": ("*OPT?", "DP8-LAN,0", "DP8-LAN,0"),
    "self_test_results": ("*TST?", "PASS,PASS,FAIL", ["PASS", "PASS", "FAIL"]),
    "temperature_test_result": (":SYST:SELF:TEST:TEMP?", "23.67", 23.67),
    "delay_end_state": (":DELAY:ENDS?", "LAST", "LAST"),
    "delay_groups": (":DELAY:GROUP?", "12", 12),
    "trigger_coupling_channels": (
        ":INST:COUP?",
        "CH1:30V/3A,CH2:30V/3A,",
        ["CH1:30V/3A", "CH2:30V/3A"],
    ),
    "selected_channel": (":INST:NSEL?", "2", 2),
    "keylock_enabled": (":SYST:KLOC:STAT?", "ON", True),
}

WRITE_PROPERTIES = {
    "standard_event_enable_register": (20, "*ESE 20"),
    "status_byte_enable_register": (32, "*SRE 32"),
    "power_on_status_clear_bit": (1, "*PSC 1"),
    "delay_end_state": ("LAST", ":DELAY:ENDS LAST"),
    "delay_groups": (12, ":DELAY:GROUP 12"),
    "trigger_coupling_channels": (["CH1", "CH2"], ":INST:COUP CH1,CH2"),
    "selected_channel": (2, ":INST CH2"),
    "keylock_enabled": (True, ":SYST:KLOC:STAT ON"),
}

CHANNEL_READS = {
    "get_voltage": (":SOUR{channel}:VOLT?", "1.2", 1.2),
    "get_current": (":SOUR{channel}:CURR?", "0.1", 0.1),
    "get_output_mode": (":OUTP:MODE?", "CV", "CV"),
    "get_output_enable": (":OUTP?", "ON", True),
    "get_output_sense_enable": (":OUTP:SENS?", "ON", True),
    "get_ocp": (":OUTP:OCP:ALAR?", "YES", True),
    "get_ocp_enable": (":OUTP:OCP?", "ON", True),
    "get_ocp_value": (":OUTP:OCP:VAL?", "0.5", 0.5),
    "get_ovp": (":OUTP:OVP:ALAR?", "NO", False),
    "get_ovp_enable": (":OUTP:OVP?", "OFF", False),
    "get_ovp_value": (":OUTP:OVP:VAL?", "5.5", 5.5),
}

CHANNEL_WRITES = {
    "set_voltage": (1.2, ":VOLT 1.2", ":SOUR2:VOLT 1.2"),
    "set_current": (0.1, ":CURR 0.1", ":SOUR2:CURR 0.1"),
    "set_output_enable": (False, ":OUTP OFF", ":OUTP  CH2,OFF"),
    "set_output_sense_enable": (False, ":OUTP:SENS OFF", ":OUTP:SENS CH2,OFF"),
    "set_ocp_enable": (True, ":OUTP:OCP ON", ":OUTP:OCP CH2,ON"),
    "set_ocp_value": (0.5, ":OUTP:OCP:VAL 0.5", ":OUTP:OCP:VAL CH2,0.5"),
    "set_ovp_enable": (True, ":OUTP:OVP ON", ":OUTP:OVP CH2,ON"),
    "set_ovp_value": (5.5, ":OUTP:OVP:VAL 5.5", ":OUTP:OVP:VAL CH2,5.5"),
}

ACTIONS = {
    "clear_event_registers": ((), "*CLS"),
    "set_opc": ((), "*OPC"),
    "reset": ((), "*RST"),
    "recall_setup": ((1,), "*RCL 1"),
    "save_setup": ((1,), "*SAV 1"),
    "trigger": ((), "*TRG"),
    "wait": ((), "*WAI"),
    "init_trigger": ((), ":INIT"),
    "install_options": (("EXAMPLE",), ":LIC:SET EXAMPLE"),
    "set_remote": ((), ":SYST:REM"),
    "set_local": ((), ":SYST:LOC"),
}


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


@pytest.mark.parametrize("name", WRITE_PROPERTIES)
def test_property_assignments(connected, name):
    driver, resource = connected
    value, command = WRITE_PROPERTIES[name]
    setattr(driver, name, value)
    assert resource.commands[-1] == command


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


def test_coupling_normalizes_field_whitespace_and_trailing_empty_field(connected):
    driver, resource = connected
    resource.responses[":INST:COUP?"] = " CH1:30V/3A , CH2:30V/3A ,  "
    assert driver.trigger_coupling_channels == ["CH1:30V/3A", "CH2:30V/3A"]


@pytest.mark.parametrize("response", ["CH1:30V/3A,,CH2:30V/3A", ",CH1:30V/3A", "ALL,,"])
def test_coupling_rejects_empty_middle_fields(connected, response):
    driver, resource = connected
    resource.responses[":INST:COUP?"] = response
    with pytest.raises(ValueError, match="Invalid trigger coupling response"):
        _ = driver.trigger_coupling_channels


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


def test_apply_full_response(connected):
    driver, resource = connected
    command = ":APPL? CH1"
    resource.responses[command] = "CH1:30V/3A,3.12,0.342"
    assert driver.get_apply(1) == ("CH1", "30V/3A", 3.12, 0.342)


def test_apply_bare_query_returns_voltage_and_current(connected):
    driver, resource = connected
    resource.responses[":APPL?"] = "3.12,0.342"
    assert driver.get_apply() == (3.12, 0.342)


@pytest.mark.parametrize(
    "channel,response",
    [
        (None, "3.12"),
        (None, "CH1:30V/3A,3.12,0.342"),
        (1, "3.12,0.342"),
        (1, "CH1,,3.12,0.342"),
        (1, "CH1,3.12,0.342"),
        (1, "CH1:,3.12,0.342"),
        (1, ":30V/3A,3.12,0.342"),
    ],
)
def test_apply_rejects_malformed_response(connected, channel, response):
    driver, resource = connected
    command = ":APPL?" + (f" CH{channel}" if channel is not None else "")
    resource.responses[command] = response
    with pytest.raises(ValueError, match="Invalid APPLy response"):
        driver.get_apply(channel)


@pytest.mark.parametrize("func", ["VOLT", "CURR"])
def test_apply_function_response(connected, func):
    driver, resource = connected
    resource.responses[f":APPL? CH2,{func}"] = "1.2"
    assert driver.get_apply(2, func) == 1.2
    resource.responses[f":APPL?,{func}"] = "1.2"
    with pytest.raises(ValueError, match="Specify a channel"):
        driver.get_apply(function=func)
