# SPDX-License-Identifier: GPL-3.0-or-later

"""Stateful virtual operation through the same public interface as hardware."""

from unittest.mock import MagicMock, patch

import pytest
import pyvisa

from dp800 import DP800Channel, InstrumentError
from virtual_dp800 import DP800
from tests.extended_api import PROPERTIES


@pytest.fixture
def supply():
    with DP800(load_resistance=10) as driver:
        driver.connect("virtual")
        # Analyzer settings require an opened recording.
        driver.set_recorder_destination(1, "TEST.ROF")
        driver.recorder_enabled = True
        driver.recorder_enabled = False
        driver.open_recording(1)
        yield driver


@pytest.mark.parametrize("exceptional", [False, True])
def test_context_manager_and_disconnected_guards(exceptional):
    driver = DP800()
    with pytest.raises(RuntimeError, match="not connected"):
        _ = driver.identity
    error = ValueError("test block")
    try:
        with driver as entered:
            assert entered is driver
            driver.connect("virtual")
            if exceptional:
                raise error
    except ValueError as raised:
        assert exceptional and raised is error
    assert not driver._connected
    driver.disconnect()
    with pytest.raises(RuntimeError):
        _ = driver.channels[1].voltage


def test_connection_uses_no_manager_and_preserves_settings():
    manager = MagicMock(spec=pyvisa.ResourceManager)
    driver = DP800()
    with patch.object(pyvisa, "ResourceManager") as factory:
        driver.connect("virtual", resource_manager=manager)
        with pytest.raises(RuntimeError, match="Already connected"):
            driver.connect("virtual")
        driver.channels[1].voltage = 2
        driver.channels[1].current = 0.2
        driver.channels[1].output_enabled = True
        view = driver.channels[1]
        driver.disconnect()
        driver.connect("virtual")
    factory.assert_not_called()
    manager.open_resource.assert_not_called()
    manager.close.assert_not_called()
    assert driver.channels[1] is view
    assert view.voltage == 2 and view.current == 0.2
    assert not view.output_enabled


@pytest.mark.parametrize(
    "kwargs",
    [{"encoding": "utf-16"}, {"read_termination": None}, {"write_termination": "\r\n"}],
)
def test_framing_conflicts_warn(kwargs):
    driver = DP800()
    with pytest.warns(UserWarning, match="will be ignored"):
        driver.connect("virtual", **kwargs)
    driver.disconnect()


@pytest.mark.parametrize(
    "name",
    [name for name, case in PROPERTIES.items() if case[4] and name != "output_range"],
)
def test_property_assignments_retain_values(supply, name):
    _, _, expected, value, _ = PROPERTIES[name]
    setattr(supply, name, value)
    assert getattr(supply, name) == expected


def test_identity_and_self_test_types_match_hardware(supply):
    assert supply.identity == ["RIGOL", "DP832A", "VIRTUAL0001", "VIRTUAL"]
    assert isinstance(supply.option_installation_status, str)
    assert supply.self_test_results == ["TopBoard:PASS", "BottomBoard:PASS", "Fan:PASS"]
    assert supply.get_board_test_results() == ["PASS", "PASS"]
    assert supply.get_board_test_results("TOP") == ["PASS"]
    assert supply.fan_test_result == "PASS"
    assert supply.temperature_test_result == 25.0


def test_channels_are_independent_and_measure_cv_cc(supply):
    channel = supply.channels[2]
    assert isinstance(channel, DP800Channel)
    channel.voltage, channel.current = 5.0, 1.0
    assert channel.measure("ALL") == ["0.0", "0.0", "0.0"]
    channel.output_enabled = True
    assert channel.output_mode == "CV"
    assert channel.measured_voltage == 5.0
    assert channel.measured_current == 0.5
    assert channel.measured_power == 2.5
    channel.current = 0.1
    assert channel.output_mode == "CC"
    assert channel.measured_voltage == 1.0
    assert channel.measured_current == 0.1
    assert supply.channels[1].voltage == 0.0
    assert supply.selected_channel == 1
    supply.selected_channel = 2
    assert supply.get_current() == 0.1


def test_open_circuit_draws_no_current():
    with DP800() as supply:
        supply.connect("virtual")
        supply.set_apply(1, 3.0, 0.1)
        supply.channels[1].output_enabled = True
        assert supply.channels[1].measure("ALL") == ["3.0", "0.0", "0.0"]


def test_steps_and_symbolic_setpoints(supply):
    channel = supply.channels[1]
    channel.voltage_step, channel.current_step = 0.2, 0.01
    channel.voltage, channel.current = 1.0, 0.1
    channel.voltage, channel.current = "UP", "DOWN"
    assert channel.voltage == pytest.approx(1.2)
    assert channel.current == pytest.approx(0.09)
    assert channel.voltage_step == 0.2 and channel.current_step == 0.01
    supply.set_voltage_step("DEF", 1)
    assert supply.get_voltage_step(1, default=True) == 0.001
    channel.voltage = "MAX"
    assert channel.voltage == 30.0


@pytest.mark.parametrize("protection", ["ocp", "ovp"])
def test_protection_alarm_and_circuit_clearing_are_distinct(supply, protection):
    channel = supply.channels[1]
    channel.voltage, channel.current = 5.0, 1.0
    setattr(channel, protection + "_value", 0.1 if protection == "ocp" else 4.0)
    setattr(channel, protection + "_enabled", True)
    channel.output_enabled = True
    assert not channel.output_enabled
    assert getattr(channel, protection + "_tripped")
    getattr(channel, "clear_" + protection + "_label")()
    assert not getattr(channel, protection + "_tripped")
    assert not channel.output_enabled
    setattr(channel, protection + "_enabled", False)
    getattr(channel, "clear_" + protection + "_circuit")()
    assert channel.output_enabled
    assert supply.get_errors() == []


def test_unsupported_channel_reports_consumable_error():
    with DP800(model="DP811") as supply:
        supply.connect("virtual")
        with pytest.raises(InstrumentError, match="Invalid channel"):
            supply.channels[2].voltage = 1.0
        assert supply.get_errors() == []
        assert supply.selected_channel == 1
        with pytest.raises(InstrumentError):
            supply.selected_channel = 2
        assert supply.selected_channel == 1


def test_error_checks_can_be_disabled():
    with DP800(check_errors=False, model="DP811") as supply:
        supply.connect("virtual")
        supply.set_voltage(1.0, 2)
        assert supply.get_errors() == ['-222,"Invalid channel"']
        assert supply.get_errors() == []


@pytest.mark.parametrize(
    "model,low,high", [("DP811", "20V/10A", "40V/5A"), ("DP813", "8V/20A", "20V/10A")]
)
def test_single_channel_ranges_and_sensing(model, low, high):
    with DP800(model=model) as supply:
        supply.connect("virtual")
        assert supply.output_range == low
        supply.output_range = "HIGH"
        assert supply.output_range == high
        supply.channels[1].sense_enabled = True
        assert supply.channels[1].sense_enabled


def test_tracking_support_and_channel_state(supply):
    supply.channels[1].tracking_enabled = True
    assert supply.channels[1].tracking_enabled
    assert not supply.channels[3].tracking_enabled
    with pytest.raises(InstrumentError):
        supply.channels[3].tracking_enabled = True


def test_display_text_coordinates_and_escaping(supply):
    supply.set_display_text('a,"b";c', 25, 35)
    assert supply.display_text == 'a,"b";c'
    supply.clear_display_text()
    assert supply.display_text == ""


def test_delay_and_timer_entries_are_independent_per_channel(supply):
    supply.set_delay_parameters(2, True, 3)
    supply.set_timer_parameters(2, 4.0, 0.2, 5.0)
    assert supply.get_delay_parameters(2) == [(2, True, 3)]
    assert supply.get_timer_parameters(2) == [(2, 4.0, 0.2, 5.0)]
    supply.selected_channel = 2
    assert supply.get_delay_parameters(2) == [(2, False, 1)]
    supply.selected_channel = 1
    supply.delay_groups = 3
    supply.delay_state_pattern = "10P"
    supply.delay_time_method = ("INC", 1, 2)
    assert supply.get_delay_parameters(0, 3) == [
        (0, True, 1),
        (1, False, 3),
        (2, True, 5),
    ]


@pytest.mark.parametrize(
    "waveform", ["SINE", "SQUARE", "RAMP", "UP", "DN", "UPDN", "RISE", "FALL"]
)
def test_timer_template_generates_entries(supply, waveform):
    supply.timer_template = waveform
    supply.timer_template_points = 10
    supply.timer_template_min, supply.timer_template_max = 1.0, 2.0
    supply.construct_timer_template()
    entries = supply.get_timer_parameters(0, 10)
    assert len(entries) == 10
    assert all(1.0 <= voltage <= 2.0 for _, voltage, _, _ in entries)
    assert supply.timer_groups == 10


def test_save_recall_lock_delete_and_reset(supply):
    channel = supply.channels[1]
    channel.voltage = 3.0
    supply.save_setup(10)
    channel.voltage = 1.0
    supply.recall_setup(10)
    assert channel.voltage == 3.0
    supply.set_memory_lock("RSF", 10, True)
    assert supply.get_memory_lock("RSF", 10)
    with pytest.raises(InstrumentError):
        supply.save_setup(10)
    supply.set_memory_lock("RSF", 10, False)
    supply.reset()
    assert not channel.output_enabled and channel.voltage == 0.0
    assert supply.memory_file_exists("RSF", 10)
    supply.recall_setup(10)
    assert channel.voltage == 3.0
    supply.delete_memory_file("RSF", 10)
    assert not supply.memory_file_exists("RSF", 10)


@pytest.mark.parametrize("kind", ["RTF", "RDF"])
def test_typed_files_round_trip(supply, kind):
    if kind == "RTF":
        supply.set_timer_parameters(0, 2.0, 0.1, 3.0)
    else:
        supply.set_delay_parameters(0, True, 3)
    supply.save_file(kind, 2)
    supply.save_file(kind, "D:\\test." + kind)
    assert "test." + kind in supply.directory_entries
    supply.recall_file(kind, 2)
    supply.recall_file(kind, "D:\\test." + kind)
    assert supply.memory_file_exists(kind, 2)


def test_external_storage_is_in_memory_and_restores_state(supply):
    supply.make_directory("D:\\bench")
    supply.directory = "D:\\bench"
    supply.channels[1].voltage = 3.0
    supply.save_file("RSF", "test.RSF")
    assert supply.directory_entries == ["test.RSF"]
    supply.channels[1].voltage = 1.0
    supply.recall_file("RSF", "test.RSF")
    assert supply.channels[1].voltage == 3.0
    supply.delete_file("test.RSF")
    assert supply.directory_entries == []
    assert supply.available_disks == ["D:\\"]


def test_preset_edit_commit_apply_and_channel_isolation(supply):
    supply.set_preset_voltage(2, 4.0)
    supply.set_preset_current(2, 0.5)
    supply.set_preset_ocp(2, True, 0.8)
    supply.set_preset_ovp(2, True, 5.0)
    supply.set_preset_otp_enabled(2, True)
    supply.set_preset_tracking_enabled(2, True)
    supply.save_preset(2)
    supply.preset_key = "USER2"
    supply.apply_preset()
    assert supply.channels[1].voltage == 4.0
    assert supply.channels[1].ocp_enabled
    assert supply.channels[1].ovp_value == 5.0
    assert supply.otp_enabled and supply.channels[1].tracking_enabled
    supply.selected_channel = 2
    assert supply.get_preset_voltage(2) == 1.0
    supply.reset_preset(2)
    assert supply.get_preset_current(2) == 0.1


def test_bus_and_immediate_triggering(supply):
    channel = supply.channels[2]
    channel.triggered_voltage, channel.triggered_current = 2.0, 0.1
    assert channel.triggered_voltage == 2.0 and channel.triggered_current == 0.1
    supply.selected_channel = 2
    supply.trigger_source = "BUS"
    supply.init_trigger()
    assert channel.voltage == 0.0
    supply.trigger()
    assert channel.voltage == 2.0 and channel.current == 0.1
    channel.triggered_voltage = 3.0
    supply.trigger_source = "IMM"
    supply.init_trigger()
    assert channel.voltage == 3.0


@pytest.mark.parametrize("line", [0, 1, 2, 3, None])
def test_digital_trigger_settings(supply, line):
    supply.set_trigger_input_enabled(True, line)
    supply.set_trigger_input_source(["CH1", "CH2"], line)
    supply.set_trigger_input_response("ALTER", line)
    supply.set_trigger_input_sensitivity("HIGH", line)
    supply.set_trigger_input_type("FALL", line)
    assert supply.get_trigger_input_enabled(line)
    assert supply.get_trigger_input_source(line) == ["CH1", "CH2"]
    assert supply.get_trigger_input_response(line) == "ALTER"
    assert supply.get_trigger_input_sensitivity(line) == "HIGH"
    assert supply.get_trigger_input_type(line) == "FALL"
    supply.set_trigger_output_enabled(True, line)
    supply.set_trigger_output_source("CH2", line)
    supply.set_trigger_output_duty_cycle(60, line)
    supply.set_trigger_output_period(0.2, line)
    supply.set_trigger_output_polarity("NEGATIVE", line)
    supply.set_trigger_output_signal("SQUARE", line)
    supply.set_trigger_output_condition(">V", 1.0, line)
    assert supply.get_trigger_output_enabled(line)
    assert supply.get_trigger_output_source(line) == "CH2"
    assert supply.get_trigger_output_duty_cycle(line) == 60
    assert supply.get_trigger_output_period(line) == 0.2
    assert supply.get_trigger_output_polarity(line) == "NEGATIVE"
    assert supply.get_trigger_output_signal(line) == "SQUARE"
    assert supply.get_trigger_output_condition(line) == (">V", 1.0)


def test_recording_and_analysis(supply):
    channel = supply.channels[1]
    channel.voltage, channel.current = 2.0, 1.0
    channel.output_enabled = True
    supply.set_recorder_destination(2, "READINGS.ROF")
    supply.recorder_period = 2
    supply.recorder_enabled = True
    channel.voltage = 4.0
    supply.recorder_enabled = False
    supply.open_recording(2)
    assert supply.get_recorded_values(2) == pytest.approx((2.0, 0.2, 0.4))
    assert supply.get_recorded_values(4) == pytest.approx((4.0, 0.4, 1.6))
    supply.analyzer_object = "V"
    supply.analyze()
    assert supply.analyzer_results["Average"] == 3.0
    assert supply.analyzer_results["Group"] == 2.0
    assert supply.get_limit("analyzer_start_time", "MIN") == 2.0
    assert supply.get_limit("analyzer_end_time", "MAX") == 4.0
    assert supply.memory_file_exists("ROF", 2)


def test_registers_and_key_locks(supply):
    supply.standard_event_enable_register = 1
    supply.set_opc()
    assert supply.status_byte_register & 32
    assert supply.get_standard_event_register() & 1
    assert supply.get_standard_event_register() == 0
    supply.set_key_lock("NUM0", True)
    assert supply.get_key_lock("NUM0")
    supply.clear_event_registers()
    assert supply.status_byte_register == 0
    supply.channels[1].questionable_enable_register = 8
    assert supply.channels[1].questionable_enable_register == 8


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "DP999"},
        {"load_resistance": 0},
        {"load_resistance": float("nan")},
        {"serial_number": "bad,serial"},
    ],
)
def test_invalid_virtual_configuration(kwargs):
    with pytest.raises(ValueError):
        DP800(**kwargs)


def test_monitor_can_disable_output_on_a_threshold(supply):
    channel = supply.channels[1]
    channel.voltage, channel.current = 3.0, 1.0
    supply.monitor_voltage_condition = (">V", "NONE")
    supply.monitor_voltage = 2.0
    supply.set_monitor_stop_action("OUTOFF", True)
    supply.monitor_enabled = True
    channel.output_enabled = True
    assert channel.output_enabled is False
    assert channel.measured_voltage == 0.0
    assert supply.monitor_stop_actions == (True, False, False)
    supply.set_monitor_stop_action("NONE", False)
    assert supply.monitor_stop_actions == (False, False, False)


def test_questionable_conditions_and_events_are_separate(supply):
    channel = supply.channels[1]
    channel.questionable_enable_register = 15
    supply.instrument_questionable_enable_register = 2
    supply.questionable_enable_register = 8192
    channel.voltage, channel.current = 5.0, 0.1
    channel.output_enabled = True
    assert channel.questionable_condition & 1  # CC mode
    assert channel.get_questionable_event() & 1
    assert channel.get_questionable_event() == 0
    assert supply.get_instrument_questionable_event() & 2
    assert supply.get_instrument_questionable_event() == 0
    assert supply.get_questionable_event() & 8192
    assert supply.get_questionable_event() == 0


def test_preset_bounds_and_partial_protection_update(supply):
    supply.set_preset_voltage(1, "MAX")
    assert supply.get_preset_voltage(1) == 30.0
    assert supply.get_preset_current(1, limit="MAX") == 3.0
    supply.set_preset_ocp(1, True, 0.5)
    supply.set_preset_ocp(1, False)
    assert supply.get_preset_ocp(1) == (False, 0.5)
    assert supply.get_preset_ocp(1, limit="MAX") == pytest.approx((False, 3.3))


def test_recorder_guards_and_external_analysis(supply):
    supply.set_recorder_destination("D:\\READINGS.ROF")
    supply.recorder_enabled = True
    with pytest.raises(InstrumentError):
        supply.recorder_period = 2
    with pytest.raises(InstrumentError):
        supply.set_recorder_destination(3, "other.ROF")
    supply.recorder_enabled = False
    supply.open_recording("D:\\READINGS.ROF")
    supply.analyzer_start_time = "MIN"
    supply.analyzer_end_time = "MAX"
    supply.analyze()
    assert supply.analyzer_results["Group"] == 2.0
    with pytest.raises(InstrumentError):
        supply.get_recorded_values(0)


def test_named_setup_and_register_clear(supply):
    supply.save_named_setup(2, "BENCH.RSF")
    assert supply.memory_file_exists("RSF", 2)
    supply.set_opc()
    supply.clear_event_registers()
    assert supply.get_standard_event_register() == 0
    supply.set_remote()
    supply.set_local()
    supply.beep()
    supply.apply_lan_config()
    supply.install_options("A" * 28)
    with pytest.raises(InstrumentError):
        supply.install_options("bad")


def test_virtual_instances_do_not_share_state():
    with DP800() as first, DP800() as second:
        first.connect("virtual")
        second.connect("virtual")
        first.channels[1].voltage = 2.0
        first.save_setup(1)
        assert second.channels[1].voltage == 0.0
        assert not second.memory_file_exists("RSF", 1)


def test_reset_restores_low_range():
    with DP800(model="DP811") as supply:
        supply.connect("virtual")
        supply.output_range = "HIGH"
        supply.reset()
        assert supply.output_range == "20V/10A"


def test_delay_cycle_default_and_timer_interlock(supply):
    supply.set_delay_cycles("N")
    assert supply.get_delay_cycles() == ("N", 1)
    supply.delay_enabled = True
    with pytest.raises(InstrumentError, match="cannot run together"):
        supply.timer_enabled = True
    assert not supply.timer_enabled
    supply.delay_enabled = False
    supply.timer_enabled = True
    assert supply.timer_enabled


@pytest.mark.parametrize("model,pair", [("DP831", (2, 3)), ("DP832", (1, 2))])
def test_voltage_tracking_supports_the_correct_channel_pair(model, pair):
    with DP800(model=model) as supply:
        supply.connect("virtual")
        supply.channels[pair[0]].tracking_enabled = True
        assert supply.channels[pair[1]].tracking_enabled
        supply.channels[pair[0]].voltage = 2.0
        assert abs(supply.channels[pair[1]].voltage) == 2.0
