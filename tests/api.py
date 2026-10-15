# SPDX-License-Identifier: GPL-3.0-or-later

"""Explicit API coverage inventory; hardware applicability is documented separately."""

import inspect


def placeholder_kwargs(method):
    """Supply the required arguments of an unfinished method without I/O."""
    values = {"enable": True, "func": "VOLT", "level": 1.0, "range": "LOW"}
    return {
        name: values[name]
        for name, param in inspect.signature(method).parameters.items()
        if param.default is inspect.Parameter.empty
    }


PLACEHOLDERS = (
    "set_delay_parameters",
    "get_delay_parameters",
    "set_delay_state",
    "get_delay_state",
    "set_delay_state_pattern",
    "get_delay_state_pattern",
    "set_delay_stop_condition",
    "get_delay_stop_condition",
    "set_delay_time_method",
    "get_delay_time_method",
    "set_output_range",
    "set_output_timer",
    "get_output_timer",
    "set_output_timer_enable",
    "get_output_timer_enable",
    "set_output_track",
    "get_output_track",
    "set_current_step",
    "get_current_step",
    "set_source_trigger",
    "get_source_trigger",
    "clear_ocp_circuit",
    "set_voltage_step",
    "get_voltage_step",
    "clear_ovp_circuit",
    "set_voltage_range",
    "set_beeper",
    "get_beeper",
    "set_gpib_config",
    "get_gpib_config",
    "set_lan_config",
    "get_lan_config",
    "set_rs232_config",
    "get_rs232_config",
    "set_contrast",
    "get_contrast",
    "set_key_keylock",
    "get_key_keylock",
    "set_language",
    "get_language",
    "set_lock",
    "get_lock",
    "set_on_off_sync",
    "get_on_off_sync",
    "set_otp_enable",
    "get_otp_enable",
    "set_power_on_config_mode",
    "get_power_on_config_mode",
    "set_brightness",
    "get_brightness",
    "set_screen_saver_enable",
    "set_track_mode",
    "get_track_mode",
    "get_scpi_version",
)

# Methods/properties exercised by lifecycle or dedicated unit/hardware scenarios.
SPECIAL_API = {
    "connect",
    "disconnect",
    "channels",
    "get_errors",
    "set_apply",
    "get_apply",
    "measure",
    "set_delay_cycles",
    "get_delay_cycles",
    "recall_setup",
    "save_setup",
    "reset",
    "install_options",
    "init_trigger",
    "trigger",
    "wait",
    "set_opc",
    "get_opc",
    "clear_event_registers",
    "get_standard_event_register",
    "set_remote",
    "set_local",
}

READ_PROPERTIES = {
    "standard_event_enable_register": ("*ESE?", "10", 10),
    "status_byte_enable_register": ("*SRE?", "32", 32),
    "status_byte_register": ("*STB?", "16", 16),
    "power_on_status_clear_bit": ("*PSC?", "1", 1),
    "identity": (
        "*IDN?",
        "RIGOL,DP832,serial,version",
        ["RIGOL", "DP832", "serial", "version"],
    ),
    "option_installation_status": ("*OPT?", "DP8-LAN,0", "DP8-LAN,0"),
    "self_test_results": ("*TST?", "PASS,PASS,FAIL", ["PASS", "PASS", "FAIL"]),
    "temperature_test_result": (":SYST:SELF:TEST:TEMP?", "23.67", 23.67),
    "delay_end_state": (":DELAY:ENDS?", "LAST", "LAST"),
    "delay_groups": (":DELAY:GROUP?", "12", 12),
    "trigger_coupling_channels": (
        ":INST:COUP?",
        "CH1:30V/3A,CH2:30V/3A",
        ["CH1:30V/3A", "CH2:30V/3A"],
    ),
    "selected_channel": (":INST:NSEL?", "2", 2),
    "keylock_enabled": (":SYST:KLOC:STAT?", "ON", True),
}

WRITE_PROPERTIES = {
    "standard_event_enable_register": (10, "*ESE 10"),
    "status_byte_enable_register": (32, "*SRE 32"),
    "power_on_status_clear_bit": (1, "*PSC 1"),
    "delay_end_state": ("LAST", ":DELAY:ENDS LAST"),
    "delay_groups": (12, ":DELAY:GROUP 12"),
    "trigger_coupling_channels": (["CH1", "CH2"], ":INST:COUP CH1,CH2"),
    "selected_channel": (2, ":INST CH2"),
    "keylock_enabled": (True, ":SYST:KLOC:STAT ON"),
}

# name: (SCPI prefix, response, parsed result)
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

# name: (value, implicit command, explicit CH2 command)
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

CHANNEL_MEMBERS = {
    "channel",
    "voltage",
    "current",
    "output_enabled",
    "output_mode",
    "sense_enabled",
    "ocp_enabled",
    "ocp_value",
    "ocp_tripped",
    "clear_ocp_label",
    "ovp_enabled",
    "ovp_value",
    "ovp_tripped",
    "clear_ovp_label",
    "measured_voltage",
    "measured_current",
    "measured_power",
    "measure",
}
