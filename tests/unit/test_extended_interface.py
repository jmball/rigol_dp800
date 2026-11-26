# SPDX-License-Identifier: GPL-3.0-or-later

"""Guide-family commands, selectors, blocks, strings, and validation."""

import pytest

from dp800.dp800 import _block, _enabled, _number

# Literal command and response cases for the extended SCPI families.
PROPERTIES = {
    "analyzer_current_time": (":ANAL:CURRT?", "1", 1, 1, ":ANAL:CURRT 1"),
    "analyzer_start_time": (":ANAL:STARTT?", "1", 1, 1, ":ANAL:STARTT 1"),
    "analyzer_end_time": (":ANAL:ENDT?", "1", 1, 1, ":ANAL:ENDT 1"),
    "analyzer_object": (":ANAL:OBJ?", "V", "V", "V", ":ANAL:OBJ V"),
    "analyzer_file": (
        ":ANAL:FILE?",
        '"D:\\test.ROF"',
        "D:\\test.ROF",
        "D:\\test.ROF",
        None,
    ),
    "analyzer_results": (
        ":ANAL:RES?",
        "Group:2,Average:1.5V,Variance:0.25V",
        {"Group": 2.0, "Average": 1.5, "Variance": 0.25},
        {"Group": 2.0, "Average": 1.5, "Variance": 0.25},
        None,
    ),
    "delay_enabled": (":DELAY?", "OFF", False, False, ":DELAY OFF"),
    "delay_state_pattern": (
        ":DELAY:STAT:GEN?",
        "01P",
        "01P",
        "01P",
        ":DELAY:STAT:GEN 01P",
    ),
    "delay_stop_condition": (
        ":DELAY:STOP?",
        "NONE",
        ("NONE", None),
        ("NONE", None),
        ":DELAY:STOP NONE",
    ),
    "delay_time_method": (
        ":DELAY:TIME:GEN?",
        "FIX,1,1",
        ("FIX", 1, 1),
        ("FIX", 1, 1),
        ":DELAY:TIME:GEN FIX,1,1",
    ),
    "display_mode": (":DISP:MODE?", "NORMAL", "NORMAL", "NORMAL", ":DISP:MODE NORMAL"),
    "display_enabled": (":DISP?", "ON", True, True, ":DISP ON"),
    "display_text": (":DISP:TEXT?", '""', "", "", None),
    "directory": (":MMEM:CDIR?", "D:\\", "D:\\", "D:\\", ':MMEM:CDIR "D:\\"'),
    "directory_entries": (
        ":MMEM:CAT?",
        '"TEST.RSF","RECORD.ROF"',
        ["TEST.RSF", "RECORD.ROF"],
        ["TEST.RSF", "RECORD.ROF"],
        None,
    ),
    "available_disks": (":MMEM:DISK?", "D:\\", ["D:\\"], ["D:\\"], None),
    "monitor_voltage": (":MONI:VOLT?", "0", 0.0, 0.0, ":MONI:VOLT 0.0"),
    "monitor_voltage_condition": (
        ":MONI:VOLT:COND?",
        "NONE,NONE",
        ("NONE", "NONE"),
        ("NONE", "NONE"),
        ":MONI:VOLT:COND NONE,NONE",
    ),
    "monitor_current": (":MONI:CURR?", "0", 0.0, 0.0, ":MONI:CURR 0.0"),
    "monitor_current_condition": (
        ":MONI:CURR:COND?",
        "NONE,NONE",
        ("NONE", "NONE"),
        ("NONE", "NONE"),
        ":MONI:CURR:COND NONE,NONE",
    ),
    "monitor_power": (":MONI:POWER?", "0", 0.0, 0.0, ":MONI:POWER 0.0"),
    "monitor_power_condition": (
        ":MONI:POWER:COND?",
        "NONE",
        "NONE",
        "NONE",
        ":MONI:POWER:COND NONE",
    ),
    "monitor_enabled": (":MONI?", "OFF", False, False, ":MONI OFF"),
    "monitor_stop_actions": (
        ":MONI:STOP?",
        "ON,OFF,ON",
        (True, False, True),
        (True, False, True),
        None,
    ),
    "output_range": (
        ":OUTP:RANG?",
        "20V/10A",
        "20V/10A",
        "20V/10A",
        ":OUTP:RANG 20V/10A",
    ),
    "preset_key": (":PRES:KEY?", "DEFAULT", "DEFAULT", "DEFAULT", ":PRES:KEY DEFAULT"),
    "recorder_enabled": (":REC?", "OFF", False, False, ":REC OFF"),
    "recorder_period": (":REC:PERI?", "1", 1, 1, ":REC:PERI 1"),
    "recorder_destination": (":REC:DEST?", "NONE", "NONE", "NONE", None),
    "questionable_condition": (":STAT:QUES:COND?", "0", 0, 0, None),
    "questionable_enable_register": (
        ":STAT:QUES:ENAB?",
        "0",
        0,
        0,
        ":STAT:QUES:ENAB 0",
    ),
    "instrument_questionable_enable_register": (
        ":STAT:QUES:INST:ENAB?",
        "0",
        0,
        0,
        ":STAT:QUES:INST:ENAB 0",
    ),
    "beeper_enabled": (":SYST:BEEP?", "ON", True, True, ":SYST:BEEP ON"),
    "brightness": (":SYST:BRIG?", "50", 50, 50, ":SYST:BRIG 50"),
    "rgb_brightness": (":SYST:RGBB?", "47", 47, 47, ":SYST:RGBB 47"),
    "contrast": (":SYST:CONT?", "50", 50, 50, ":SYST:CONT 50"),
    "gpib_address": (":SYST:COMM:GPIB:ADDR?", "1", 1, 1, ":SYST:COMM:GPIB:ADDR 1"),
    "lan_autoip_enabled": (
        ":SYST:COMM:LAN:AUTO?",
        "ON",
        True,
        True,
        ":SYST:COMM:LAN:AUTO ON",
    ),
    "lan_dhcp_enabled": (
        ":SYST:COMM:LAN:DHCP?",
        "ON",
        True,
        True,
        ":SYST:COMM:LAN:DHCP ON",
    ),
    "lan_dns": (
        ":SYST:COMM:LAN:DNS?",
        "0.0.0.0",
        "0.0.0.0",
        "0.0.0.0",
        ":SYST:COMM:LAN:DNS 0.0.0.0",
    ),
    "lan_gateway": (
        ":SYST:COMM:LAN:GATE?",
        "0.0.0.0",
        "0.0.0.0",
        "0.0.0.0",
        ":SYST:COMM:LAN:GATE 0.0.0.0",
    ),
    "lan_ip_address": (
        ":SYST:COMM:LAN:IPAD?",
        "192.0.2.1",
        "192.0.2.1",
        "192.0.2.1",
        ":SYST:COMM:LAN:IPAD 192.0.2.1",
    ),
    "lan_mac_address": (
        ":SYST:COMM:LAN:MAC?",
        "00-00-00-00-00-01",
        "00-00-00-00-00-01",
        "00-00-00-00-00-01",
        None,
    ),
    "lan_manualip_enabled": (
        ":SYST:COMM:LAN:MAN?",
        "OFF",
        False,
        False,
        ":SYST:COMM:LAN:MAN OFF",
    ),
    "lan_subnet_mask": (
        ":SYST:COMM:LAN:SMASK?",
        "255.255.255.0",
        "255.255.255.0",
        "255.255.255.0",
        ":SYST:COMM:LAN:SMASK 255.255.255.0",
    ),
    "rs232_baud_rate": (
        ":SYST:COMM:RS232:BAUD?",
        "9600",
        9600,
        9600,
        ":SYST:COMM:RS232:BAUD 9600",
    ),
    "rs232_data_bits": (
        ":SYST:COMM:RS232:DATAB?",
        "8",
        8,
        8,
        ":SYST:COMM:RS232:DATAB 8",
    ),
    "rs232_flow_control_enabled": (
        ":SYST:COMM:RS232:FLOWC?",
        "OFF",
        False,
        False,
        ":SYST:COMM:RS232:FLOWC OFF",
    ),
    "rs232_parity": (
        ":SYST:COMM:RS232:PARI?",
        "NONE",
        "NONE",
        "NONE",
        ":SYST:COMM:RS232:PARI NONE",
    ),
    "rs232_stop_bits": (
        ":SYST:COMM:RS232:STOPB?",
        "1",
        1,
        1,
        ":SYST:COMM:RS232:STOPB 1",
    ),
    "language": (":SYST:LANG:TYPE?", "English", "English", "EN", ":SYST:LANG:TYPE EN"),
    "locked": (":SYST:LOCK?", "OFF", False, False, ":SYST:LOCK OFF"),
    "on_off_sync_enabled": (":SYST:ONOFFS?", "OFF", False, False, ":SYST:ONOFFS OFF"),
    "otp_enabled": (":SYST:OTP?", "OFF", False, False, ":SYST:OTP OFF"),
    "power_on_config_mode": (
        ":SYST:POWE?",
        "DEFAULT",
        "DEFAULT",
        "DEFAULT",
        ":SYST:POWE DEFAULT",
    ),
    "screen_saver_enabled": (":SYST:SAV?", "OFF", False, False, ":SYST:SAV OFF"),
    "track_mode": (":SYST:TRACKM?", "SYNC", "SYNC", "SYNC", ":SYST:TRACKM SYNC"),
    "scpi_version": (":SYST:VERS?", "1999.0", "1999.0", "1999.0", None),
    "fan_test_result": (":SYST:SELF:TEST:FAN?", "PASS", "PASS", "PASS", None),
    "timer_cycles": (":TIME:CYCLE?", "N,1", ("N", 1), ("N", 1), ":TIME:CYCLE N,1"),
    "timer_end_state": (":TIME:ENDS?", "OFF", "OFF", "OFF", ":TIME:ENDS OFF"),
    "timer_groups": (":TIME:GROUP?", "1", 1, 1, ":TIME:GROUP 1"),
    "timer_enabled": (":TIME?", "OFF", False, False, ":TIME OFF"),
    "timer_template": (
        ":TIME:TEMP:SEL?",
        "SINE",
        "SINE",
        "SINE",
        ":TIME:TEMP:SEL SINE",
    ),
    "timer_template_object": (
        ":TIME:TEMP:OBJ?",
        "V,0.1",
        ("V", 0.1),
        ("V", 0.1),
        ":TIME:TEMP:OBJ V,0.1",
    ),
    "timer_template_max": (":TIME:TEMP:MAXV?", "1", 1.0, 1.0, ":TIME:TEMP:MAXV 1.0"),
    "timer_template_min": (":TIME:TEMP:MINV?", "0", 0.0, 0.0, ":TIME:TEMP:MINV 0.0"),
    "timer_template_inverted": (
        ":TIME:TEMP:INVE?",
        "OFF",
        False,
        False,
        ":TIME:TEMP:INVE OFF",
    ),
    "timer_template_fall_rate": (":TIME:TEMP:FALLR?", "0", 0, 0, ":TIME:TEMP:FALLR 0"),
    "timer_template_rise_rate": (":TIME:TEMP:RISER?", "0", 0, 0, ":TIME:TEMP:RISER 0"),
    "timer_template_interval": (":TIME:TEMP:INTE?", "1", 1, 1, ":TIME:TEMP:INTE 1"),
    "timer_template_period": (":TIME:TEMP:PERI?", "10", 10, 10, ":TIME:TEMP:PERI 10"),
    "timer_template_points": (":TIME:TEMP:POINT?", "10", 10, 10, ":TIME:TEMP:POINT 10"),
    "timer_template_symmetry": (":TIME:TEMP:SYMM?", "50", 50, 50, ":TIME:TEMP:SYMM 50"),
    "timer_template_width": (":TIME:TEMP:WIDT?", "1", 1, 1, ":TIME:TEMP:WIDT 1"),
    "trigger_source": (":TRIG:SOUR?", "BUS", "BUS", "BUS", ":TRIG:SOUR BUS"),
    "trigger_delay": (":TRIG:DEL?", "0", 0.0, 0.0, ":TRIG:DEL 0.0"),
}

METHODS = [
    ("analyze", (), {}, ":ANAL:ANAL", None, None),
    ("open_recording", (2,), {}, ":ANAL:MEM 2", None, None),
    (
        "open_recording",
        ("D:\\record.ROF",),
        {},
        ':ANAL:MMEM "D:\\record.ROF"',
        None,
        None,
    ),
    (
        "get_recorded_values",
        (3,),
        {},
        ":ANAL:VAL? 3",
        "Volt:1.5V,Curr:0.2A,Power:0.3W",
        (1.5, 0.2, 0.3),
    ),
    ("set_delay_parameters", (2, True, 3), {}, ":DELAY:PARA 2,ON,3", None, None),
    (
        "get_delay_parameters",
        (2, 2),
        {},
        ":DELAY:PARA? 2,2",
        "#90000000152,ON,3;3,OFF,4;",
        [(2, True, 3), (3, False, 4)],
    ),
    (
        "set_display_text",
        ('a,"b";c', 25, 35),
        {},
        ':DISP:TEXT "a,""b"";c",25,35',
        None,
        None,
    ),
    ("clear_display_text", (), {}, ":DISP:TEXT:CLE", None, None),
    ("save_file", ("RSF", 2), {}, ":MEM:STOR RSF,2", None, None),
    ("save_file", ("RSF", "D:\\file.RSF"), {}, ':MMEM:STOR "D:\\file.RSF"', None, None),
    ("save_file", ("RTF", 2), {}, ":MEM:STOR RTF,2", None, None),
    ("save_file", ("RTF", "D:\\file.RTF"), {}, ':MMEM:STOR "D:\\file.RTF"', None, None),
    ("save_file", ("RDF", 2), {}, ":MEM:STOR RDF,2", None, None),
    ("save_file", ("RDF", "D:\\file.RDF"), {}, ':MMEM:STOR "D:\\file.RDF"', None, None),
    ("recall_file", ("RSF", 2), {}, ":MEM:LOAD RSF,2", None, None),
    (
        "recall_file",
        ("RSF", "D:\\file.RSF"),
        {},
        ':MMEM:LOAD "D:\\file.RSF"',
        None,
        None,
    ),
    ("recall_file", ("RTF", 2), {}, ":MEM:LOAD RTF,2", None, None),
    (
        "recall_file",
        ("RTF", "D:\\file.RTF"),
        {},
        ':MMEM:LOAD "D:\\file.RTF"',
        None,
        None,
    ),
    ("recall_file", ("RDF", 2), {}, ":MEM:LOAD RDF,2", None, None),
    (
        "recall_file",
        ("RDF", "D:\\file.RDF"),
        {},
        ':MMEM:LOAD "D:\\file.RDF"',
        None,
        None,
    ),
    ("delete_memory_file", ("ROF", 2), {}, ":MEM:DEL ROF,2", None, None),
    ("set_memory_lock", ("RSF", 2, True), {}, ":MEM:LOCK RSF,2,ON", None, None),
    ("get_memory_lock", ("RSF", 2), {}, ":MEM:LOCK? RSF,2", "YES", True),
    ("memory_file_exists", ("RDF", 2), {}, ":MEM:VAL? RDF,2", "NO", False),
    ("make_directory", ("D:\\test",), {}, ':MMEM:MDIR "D:\\test"', None, None),
    ("delete_file", ("D:\\test.RSF",), {}, ':MMEM:DEL "D:\\test.RSF"', None, None),
    (
        "set_monitor_stop_action",
        ("OUTOFF", True),
        {},
        ":MONI:STOP OUTOFF,ON",
        None,
        None,
    ),
    ("set_output_track", (True,), {"channel": None}, ":OUTP:TRAC ON", None, None),
    ("set_output_track", (True,), {"channel": 2}, ":OUTP:TRAC CH2,ON", None, None),
    ("get_output_track", (), {"channel": None}, ":OUTP:TRAC?", "ON", True),
    ("get_output_track", (), {"channel": 2}, ":OUTP:TRAC? CH2", "ON", True),
    ("apply_preset", (), {}, ":PRES", None, None),
    ("reset_preset", (2,), {}, ":PRES:USER2:SET:DEF", None, None),
    ("save_preset", (2,), {}, ":PRES:USER2:SET:SURE", None, None),
    ("set_preset_voltage", (2, 1.5), {}, ":PRES:USER2:SET:VOLT 1.5", None, None),
    ("get_preset_voltage", (2,), {}, ":PRES:USER2:SET:VOLT?", "1.500", 1.5),
    ("set_preset_current", (2, 0.2), {}, ":PRES:USER2:SET:CURR 0.2", None, None),
    ("get_preset_current", (2,), {}, ":PRES:USER2:SET:CURR?", "0.2000", 0.2),
    ("set_preset_otp_enabled", (2, True), {}, ":PRES:USER2:SET:OTP ON", None, None),
    ("get_preset_otp_enabled", (2,), {}, ":PRES:USER2:SET:OTP?", "ON", True),
    (
        "set_preset_tracking_enabled",
        (2, True),
        {},
        ":PRES:USER2:SET:TRAC ON",
        None,
        None,
    ),
    ("get_preset_tracking_enabled", (2,), {}, ":PRES:USER2:SET:TRAC?", "ON", True),
    ("set_preset_ocp", (2, True, 1.5), {}, ":PRES:USER2:SET:OCP ON,1.5", None, None),
    ("get_preset_ocp", (2,), {}, ":PRES:USER2:SET:OCP?", "ON,1.500", (True, 1.5)),
    ("set_preset_ovp", (2, True, 1.5), {}, ":PRES:USER2:SET:OVP ON,1.5", None, None),
    ("get_preset_ovp", (2,), {}, ":PRES:USER2:SET:OVP?", "ON,1.500", (True, 1.5)),
    (
        "set_recorder_destination",
        (2, "test.ROF"),
        {},
        ':REC:MEM 2,"test.ROF"',
        None,
        None,
    ),
    (
        "set_recorder_destination",
        ("D:\\test.ROF",),
        {},
        ':REC:MMEM "D:\\test.ROF"',
        None,
        None,
    ),
    ("set_voltage_step", (0.1,), {"channel": None}, ":VOLT:STEP 0.1", None, None),
    ("get_voltage_step", (), {"channel": None}, ":VOLT:STEP?", "0.100", 0.1),
    ("clear_ovp_circuit", (), {"channel": None}, ":VOLT:PROT:CLE", None, None),
    (
        "set_source_trigger",
        ("VOLT", 1.5),
        {"channel": None},
        ":VOLT:TRIG 1.5",
        None,
        None,
    ),
    ("get_source_trigger", ("VOLT",), {"channel": None}, ":VOLT:TRIG?", "1.500V", 1.5),
    ("set_voltage_step", (0.1,), {"channel": 2}, ":SOUR2:VOLT:STEP 0.1", None, None),
    ("get_voltage_step", (), {"channel": 2}, ":SOUR2:VOLT:STEP?", "0.100", 0.1),
    ("clear_ovp_circuit", (), {"channel": 2}, ":SOUR2:VOLT:PROT:CLE", None, None),
    (
        "set_source_trigger",
        ("VOLT", 1.5),
        {"channel": 2},
        ":SOUR2:VOLT:TRIG 1.5",
        None,
        None,
    ),
    (
        "get_source_trigger",
        ("VOLT",),
        {"channel": 2},
        ":SOUR2:VOLT:TRIG?",
        "1.500V",
        1.5,
    ),
    ("set_current_step", (0.1,), {"channel": None}, ":CURR:STEP 0.1", None, None),
    ("get_current_step", (), {"channel": None}, ":CURR:STEP?", "0.100", 0.1),
    ("clear_ocp_circuit", (), {"channel": None}, ":CURR:PROT:CLE", None, None),
    (
        "set_source_trigger",
        ("CURR", 1.5),
        {"channel": None},
        ":CURR:TRIG 1.5",
        None,
        None,
    ),
    ("get_source_trigger", ("CURR",), {"channel": None}, ":CURR:TRIG?", "1.500A", 1.5),
    ("set_current_step", (0.1,), {"channel": 2}, ":SOUR2:CURR:STEP 0.1", None, None),
    ("get_current_step", (), {"channel": 2}, ":SOUR2:CURR:STEP?", "0.100", 0.1),
    ("clear_ocp_circuit", (), {"channel": 2}, ":SOUR2:CURR:PROT:CLE", None, None),
    (
        "set_source_trigger",
        ("CURR", 1.5),
        {"channel": 2},
        ":SOUR2:CURR:TRIG 1.5",
        None,
        None,
    ),
    (
        "get_source_trigger",
        ("CURR",),
        {"channel": 2},
        ":SOUR2:CURR:TRIG?",
        "1.500A",
        1.5,
    ),
    ("get_questionable_event", (), {}, ":STAT:QUES?", "4", 4),
    ("get_instrument_questionable_event", (), {}, ":STAT:QUES:INST?", "4", 4),
    (
        "get_channel_questionable_condition",
        (2,),
        {},
        ":STAT:QUES:INST:ISUM2:COND?",
        "8",
        8,
    ),
    (
        "get_channel_questionable_enable",
        (2,),
        {},
        ":STAT:QUES:INST:ISUM2:ENAB?",
        "8",
        8,
    ),
    ("get_channel_questionable_event", (2,), {}, ":STAT:QUES:INST:ISUM2:EVEN?", "8", 8),
    (
        "set_channel_questionable_enable",
        (8, 2),
        {},
        ":STAT:QUES:INST:ISUM2:ENAB 8",
        None,
        None,
    ),
    ("save_named_setup", (2, "test.RSF"), {}, ':STOR:LOC 2,"test.RSF"', None, None),
    ("beep", (), {}, ":SYST:BEEP:IMM", None, None),
    ("apply_lan_config", (), {}, ":SYST:COMM:LAN:APPL", None, None),
    ("set_key_lock", ("CH1", True), {}, ":SYST:KLOC CH1,ON", None, None),
    ("get_key_lock", ("CH1",), {}, ":SYST:KLOC? CH1", "1", True),
    (
        "get_board_test_results",
        (),
        {},
        ":SYST:SELF:TEST:BOARD?",
        "PASS,FAIL",
        ["PASS", "FAIL"],
    ),
    (
        "get_board_test_results",
        ("TOP",),
        {},
        ":SYST:SELF:TEST:BOARD? TOP",
        "PASS",
        ["PASS"],
    ),
    ("construct_timer_template", (), {}, ":TIME:TEMP:CONST", None, None),
    (
        "set_timer_parameters",
        (2, 1.5, 0.1, 4),
        {},
        ":TIME:PARA 2,1.5,0.1,4",
        None,
        None,
    ),
    (
        "get_timer_parameters",
        (2, 1),
        {},
        ":TIME:PARA? 2,1",
        "#90000000122,1.5,0.1,4;",
        [(2, 1.5, 0.1, 4.0)],
    ),
    ("set_trigger_input_enabled", (True,), {"line": 2}, ":TRIG:IN D2,ON", None, None),
    ("get_trigger_input_enabled", (), {"line": 2}, ":TRIG:IN? D2", "D2,ON", True),
    (
        "set_trigger_input_source",
        (["CH1", "CH2"],),
        {"line": 2},
        ":TRIG:IN:SOUR D2,CH1,CH2",
        None,
        None,
    ),
    (
        "get_trigger_input_source",
        (),
        {"line": 2},
        ":TRIG:IN:SOUR? D2",
        "CH1,CH2",
        ["CH1", "CH2"],
    ),
    (
        "set_trigger_input_response",
        ("ALTER",),
        {"line": 2},
        ":TRIG:IN:RESP D2,ALTER",
        None,
        None,
    ),
    (
        "get_trigger_input_response",
        (),
        {"line": 2},
        ":TRIG:IN:RESP? D2",
        "ALTER",
        "ALTER",
    ),
    (
        "set_trigger_input_sensitivity",
        ("HIGH",),
        {"line": 2},
        ":TRIG:IN:SENS D2,HIGH",
        None,
        None,
    ),
    (
        "get_trigger_input_sensitivity",
        (),
        {"line": 2},
        ":TRIG:IN:SENS? D2",
        "HIGH",
        "HIGH",
    ),
    (
        "set_trigger_input_type",
        ("FALL",),
        {"line": 2},
        ":TRIG:IN:TYPE D2,FALL",
        None,
        None,
    ),
    ("get_trigger_input_type", (), {"line": 2}, ":TRIG:IN:TYPE? D2", "FALL", "FALL"),
    ("set_trigger_output_enabled", (True,), {"line": 2}, ":TRIG:OUT D2,ON", None, None),
    ("get_trigger_output_enabled", (), {"line": 2}, ":TRIG:OUT? D2", "D2,ON", True),
    (
        "set_trigger_output_source",
        ("CH2",),
        {"line": 2},
        ":TRIG:OUT:SOUR D2,CH2",
        None,
        None,
    ),
    ("get_trigger_output_source", (), {"line": 2}, ":TRIG:OUT:SOUR? D2", "CH2", "CH2"),
    (
        "set_trigger_output_duty_cycle",
        (50,),
        {"line": 2},
        ":TRIG:OUT:DUTY D2,50",
        None,
        None,
    ),
    ("get_trigger_output_duty_cycle", (), {"line": 2}, ":TRIG:OUT:DUTY? D2", "50", 50),
    (
        "set_trigger_output_period",
        (0.1,),
        {"line": 2},
        ":TRIG:OUT:PERI D2,0.1",
        None,
        None,
    ),
    (
        "get_trigger_output_period",
        (),
        {"line": 2},
        ":TRIG:OUT:PERI? D2",
        "0.100000",
        0.1,
    ),
    (
        "set_trigger_output_polarity",
        ("NEGATIVE",),
        {"line": 2},
        ":TRIG:OUT:POLA D2,NEGATIVE",
        None,
        None,
    ),
    (
        "get_trigger_output_polarity",
        (),
        {"line": 2},
        ":TRIG:OUT:POLA? D2",
        "NEGATIVE",
        "NEGATIVE",
    ),
    (
        "set_trigger_output_signal",
        ("SQUARE",),
        {"line": 2},
        ":TRIG:OUT:SIGN D2,SQUARE",
        None,
        None,
    ),
    (
        "get_trigger_output_signal",
        (),
        {"line": 2},
        ":TRIG:OUT:SIGN? D2",
        "SQUARE",
        "SQUARE",
    ),
    (
        "set_trigger_output_condition",
        (">V", 1.5),
        {"line": 2},
        ":TRIG:OUT:COND D2,>V,1.5",
        None,
        None,
    ),
    (
        "get_trigger_output_condition",
        (),
        {"line": 2},
        ":TRIG:OUT:COND? D2",
        ">V,1.500",
        (">V", 1.5),
    ),
    ("get_limit", ("brightness", "MAX"), {}, ":SYST:BRIG? MAX", "100", 100.0),
    ("get_limit", ("rgb_brightness", "MIN"), {}, ":SYST:RGBB? MIN", "1", 1.0),
]


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


@pytest.mark.parametrize("name", [name for name, case in PROPERTIES.items() if case[4]])
def test_property_assignment_contract(connected, name):
    driver, resource = connected
    _, _, _, value, command = PROPERTIES[name]
    setattr(driver, name, value)
    assert resource.commands[-1] == command


@pytest.mark.parametrize("case", METHODS, ids=lambda case: case[0] + "-" + case[3])
def test_method_contract(connected, case):
    driver, resource = connected
    name, args, kwargs, command, raw, expected = case
    if raw is not None:
        resource.responses[command] = raw
    assert getattr(driver, name)(*args, **kwargs) == expected
    assert resource.commands[-1] == command


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
        # Guide setting codes only; query names such as English are not codes.
        lambda d: setattr(d, "language", "English"),
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
