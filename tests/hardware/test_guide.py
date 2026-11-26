# SPDX-License-Identifier: GPL-3.0-or-later

"""Extended round trips on a bench with the relevant options installed.

--hardware-guide enables this module. File/preset writes additionally require a
scratch slot/directory/preset. Communication changes and key locking are covered
with fakes and the virtual supply, as they can interrupt the active test session.
"""

import ntpath
import time
import uuid

import pytest

from dp800 import LANGUAGE_NAMES

pytestmark = pytest.mark.hardware


@pytest.fixture(autouse=True)
def require_extended_suite(pytestconfig):
    if not pytestconfig.getoption("--hardware-guide"):
        pytest.skip("extended guide cases require --hardware-guide")


# Same-value assignments exercise guide settings while preserving the bench
# configuration and avoiding communication, lock, output, and storage changes.
ROUND_TRIP_PROPERTIES = (
    "delay_state_pattern",
    "delay_stop_condition",
    "delay_time_method",
    "display_mode",
    "display_enabled",
    "preset_key",
    "questionable_enable_register",
    pytest.param(
        "instrument_questionable_enable_register",
        marks=pytest.mark.supported_on("multi_channel"),
    ),
    "brightness",
    "rgb_brightness",
    "contrast",
    "beeper_enabled",
    "on_off_sync_enabled",
    "otp_enabled",
    "power_on_config_mode",
    "screen_saver_enabled",
    "track_mode",
    "timer_cycles",
    "timer_end_state",
    "timer_groups",
    "timer_template",
    "timer_template_object",
    "timer_template_max",
    "timer_template_min",
    "timer_template_inverted",
    "timer_template_fall_rate",
    "timer_template_rise_rate",
    "timer_template_interval",
    "timer_template_period",
    "timer_template_points",
    "timer_template_symmetry",
    "timer_template_width",
)


# Settings of the selected channel's monitor; requires the monitor option.
MONITOR_PROPERTIES = (
    "monitor_voltage",
    "monitor_voltage_condition",
    "monitor_current",
    "monitor_current_condition",
    "monitor_power",
    "monitor_power_condition",
    "monitor_enabled",
)


def assert_round_trip(supply, name):
    original = getattr(supply, name)
    setattr(supply, name, original)
    actual = getattr(supply, name)
    assert (
        actual == pytest.approx(original)
        if isinstance(original, (int, float))
        else actual == original
    )


@pytest.mark.parametrize("name", ROUND_TRIP_PROPERTIES)
def test_extended_property_round_trip(hardware, name):
    assert_round_trip(hardware, name)


@pytest.mark.requires_option("DP8-MONITOR")
@pytest.mark.parametrize("name", MONITOR_PROPERTIES)
def test_monitor_property_round_trip(hardware, name):
    assert_round_trip(hardware, name)


@pytest.mark.requires_option("DP8-MONITOR")
def test_monitor_enable_and_stop_actions(hardware):
    # Outputs are off, so an output-off stop action cannot change the bench.
    enabled, actions = hardware.monitor_enabled, hardware.monitor_stop_actions
    try:
        for state in (not enabled, enabled):
            hardware.monitor_enabled = state
            assert hardware.monitor_enabled is state
        for action, state in zip(("OUTOFF", "WARN", "BEEPER"), actions):
            hardware.set_monitor_stop_action(action, state)
        assert hardware.monitor_stop_actions == actions
    finally:
        hardware.monitor_enabled = enabled
        for action, state in zip(("OUTOFF", "WARN", "BEEPER"), actions):
            hardware.set_monitor_stop_action(action, state)


def test_language_code_reads_back_as_guide_name(hardware):
    # The guide sets codes (EN) and its query returns names (English).
    original = hardware.language
    code = {name: code for code, name in LANGUAGE_NAMES.items()}[original]
    hardware.language = code
    assert hardware.language == LANGUAGE_NAMES[code] == original


def test_system_information_and_self_tests(hardware):
    assert isinstance(hardware.scpi_version, str) and hardware.scpi_version
    assert hardware.fan_test_result.upper() == "PASS"
    assert [item.upper() for item in hardware.get_board_test_results()] == [
        "PASS",
        "PASS",
    ]
    for board in ("TOP", "BOTTOM"):
        assert [item.upper() for item in hardware.get_board_test_results(board)] == [
            "PASS"
        ]
    hardware.beep()


def test_questionable_event_read(hardware):
    assert hardware.get_questionable_event() >= 0  # Consumes the event register.


@pytest.mark.supported_on("multi_channel")
def test_instrument_and_channel_questionable_registers(hardware, bench_config):
    assert hardware.get_instrument_questionable_event() >= 0
    for number in bench_config.channels:
        original = hardware.get_channel_questionable_enable(number)
        try:
            hardware.set_channel_questionable_enable(original, number)
            assert hardware.get_channel_questionable_enable(number) == original
            assert hardware.get_channel_questionable_condition(number) >= 0
            assert hardware.get_channel_questionable_event(number) >= 0
        finally:
            hardware.set_channel_questionable_enable(original, number)


def test_individual_key_lock(hardware):
    original = hardware.get_key_lock("HELP")
    try:
        for state in (True, False):
            hardware.set_key_lock("HELP", state)
            assert hardware.get_key_lock("HELP") is state
    finally:
        hardware.set_key_lock("HELP", original)


def test_display_text(hardware):
    text = "DP800 TEST"
    try:
        hardware.set_display_text(text, 5, 110)
        assert hardware.display_text == text
    finally:
        hardware.clear_display_text()
    assert hardware.display_text != text


def test_step_sizes(hardware, bench_config):
    for number in bench_config.channels:
        for quantity in ("voltage", "current"):
            get = getattr(hardware, f"get_{quantity}_step")
            set_ = getattr(hardware, f"set_{quantity}_step")
            original = get(number)
            try:
                assert get(number, default=True) > 0
                set_(original, number)
                assert get(number) == pytest.approx(original)
            finally:
                set_(original, number)


@pytest.mark.supported_on("tracking")
def test_output_tracking(hardware, bench_config):
    channels = bench_config.supported_channels("tracking")
    if not channels:
        pytest.skip("--hardware-channels excludes the tracking channels")
    original = {number: hardware.get_output_track(number) for number in channels}
    try:
        for number in channels:
            for state in (True, False):
                hardware.set_output_track(state, number)
                assert hardware.get_output_track(number) is state
    finally:
        for number, state in original.items():
            hardware.set_output_track(state, number)


# Digital line settings use same-value writes, so no line is enabled or driven.
DIGITAL_LINE_SETTINGS = (
    "trigger_input_enabled",
    "trigger_input_source",
    "trigger_input_response",
    "trigger_input_sensitivity",
    "trigger_input_type",
    "trigger_output_enabled",
    "trigger_output_source",
    "trigger_output_duty_cycle",
    "trigger_output_period",
    "trigger_output_polarity",
    "trigger_output_signal",
)


@pytest.mark.requires_option("DP8-TRIGGER")
@pytest.mark.parametrize("line", range(4), ids=lambda line: f"D{line}")
def test_digital_line_settings_round_trip(hardware, line):
    for setting in DIGITAL_LINE_SETTINGS:
        original = getattr(hardware, f"get_{setting}")(line)
        getattr(hardware, f"set_{setting}")(original, line=line)
        actual = getattr(hardware, f"get_{setting}")(line)
        assert (
            actual == pytest.approx(original)
            if isinstance(original, float)
            else actual == original
        ), setting
    condition, value = hardware.get_trigger_output_condition(line)
    hardware.set_trigger_output_condition(condition, value, line=line)
    assert hardware.get_trigger_output_condition(line) == (condition, value)


def test_delay_and_timer_entries(hardware):
    hardware.timer_enabled = False
    hardware.delay_enabled = False
    timer = hardware.get_timer_parameters(0)
    delay = hardware.get_delay_parameters(0)
    try:
        hardware.set_timer_parameters(0, 1.0, 0.01, 1.0)
        assert hardware.get_timer_parameters(0) == [(0, 1.0, 0.01, 1.0)]
        hardware.set_delay_parameters(0, False, 2)
        assert hardware.get_delay_parameters(0) == [(0, False, 2)]
    finally:
        for args in timer:
            hardware.set_timer_parameters(*args)
        for args in delay:
            hardware.set_delay_parameters(*args)


def test_template_construction(hardware):
    hardware.timer_enabled = False
    count = hardware.timer_groups
    original = hardware.get_timer_parameters(0, count)
    try:
        hardware.construct_timer_template()
        generated = hardware.get_timer_parameters(0, hardware.timer_groups)
        assert len(generated) == hardware.timer_groups
    finally:
        for args in original:
            hardware.set_timer_parameters(*args)
        hardware.timer_groups = count


def test_typed_internal_storage(hardware, bench_config):
    if bench_config.save_slot is None:
        pytest.skip("typed storage writes require --hardware-save-slot")
    for kind in ("RTF", "RDF"):
        hardware.save_file(kind, bench_config.save_slot)
        assert hardware.memory_file_exists(kind, bench_config.save_slot)
        hardware.set_memory_lock(kind, bench_config.save_slot, True)
        try:
            assert hardware.get_memory_lock(kind, bench_config.save_slot)
        finally:
            hardware.set_memory_lock(kind, bench_config.save_slot, False)
        hardware.recall_file(kind, bench_config.save_slot)
        hardware.delete_memory_file(kind, bench_config.save_slot)
        assert not hardware.memory_file_exists(kind, bench_config.save_slot)


def test_external_storage(hardware, pytestconfig):
    directory = pytestconfig.getoption("--hardware-directory")
    if directory is None:
        pytest.skip("external file writes require --hardware-directory")
    original = hardware.directory
    try:
        hardware.directory = directory
        for kind in ("RSF", "RTF", "RDF"):
            filename = f"DP8TEST.{kind}"
            hardware.save_file(kind, filename)
            hardware.recall_file(kind, filename)
            assert any(filename in entry for entry in hardware.directory_entries)
            hardware.delete_file(filename)
    finally:
        hardware.directory = original


def record(supply, location, filename=None):
    if filename is None:
        supply.set_recorder_destination(location)
    else:
        supply.set_recorder_destination(location, filename)
    assert "DP8TEST" in supply.recorder_destination.upper()
    period = supply.recorder_period
    try:
        supply.recorder_period = 1
        supply.recorder_enabled = True
        time.sleep(2.1)  # Produce real samples; not an error-query delay.
    finally:
        supply.recorder_enabled = False
        supply.recorder_period = period


def check_analyzer(supply):
    assert "DP8TEST" in supply.analyzer_file.upper()
    start, end = supply.analyzer_start_time, supply.analyzer_end_time
    supply.analyzer_object = supply.analyzer_object
    supply.analyzer_start_time, supply.analyzer_end_time = start, end
    assert (supply.analyzer_start_time, supply.analyzer_end_time) == (start, end)
    supply.analyzer_current_time = start
    assert supply.analyzer_current_time == start
    supply.analyze()
    assert supply.analyzer_results["Group"] >= 1
    assert len(supply.get_recorded_values(start)) == 3


@pytest.mark.requires_option("DP8-ANALYZER")
def test_recording_and_analyzer(hardware, bench_config):
    if bench_config.save_slot is None:
        pytest.skip("recording overwrites ROF data in --hardware-save-slot")
    record(hardware, bench_config.save_slot, "DP8TEST.ROF")
    hardware.open_recording(bench_config.save_slot)
    check_analyzer(hardware)


@pytest.mark.requires_option("DP8-ANALYZER")
def test_external_recording_and_analyzer(hardware, pytestconfig):
    directory = pytestconfig.getoption("--hardware-directory")
    if directory is None:
        pytest.skip("external recording requires --hardware-directory")
    original = hardware.directory
    path = ntpath.join(directory, "DP8TEST.ROF")
    try:
        record(hardware, path)
        hardware.open_recording(path)
        check_analyzer(hardware)
    finally:
        hardware.directory = directory
        if any("DP8TEST.ROF" in entry for entry in hardware.directory_entries):
            hardware.delete_file("DP8TEST.ROF")
        hardware.directory = original


def test_named_setup(hardware, bench_config):
    if bench_config.save_slot is None:
        pytest.skip("named state storage requires --hardware-save-slot")
    hardware.save_named_setup(bench_config.save_slot, "DP8TEST")
    assert hardware.memory_file_exists("RSF", bench_config.save_slot)


def test_external_disks_and_directories(hardware, pytestconfig):
    directory = pytestconfig.getoption("--hardware-directory")
    if directory is None:
        pytest.skip("external directory writes require --hardware-directory")
    assert hardware.available_disks
    original = hardware.directory
    name = "DP8" + uuid.uuid4().hex[:5].upper()  # Guide limit: 9 characters.
    try:
        hardware.directory = directory
        hardware.make_directory(name)
        assert any(name in entry for entry in hardware.directory_entries)
    finally:
        hardware.directory = directory
        if any(name in entry for entry in hardware.directory_entries):
            hardware.delete_file(name)  # Deletes the empty folder.
        hardware.directory = original


def test_user_preset(hardware, pytestconfig):
    preset = pytestconfig.getoption("--hardware-preset")
    if preset is None:
        pytest.skip("preset edits require --hardware-preset")
    original = hardware.get_preset_voltage(preset), hardware.get_preset_current(preset)
    key = hardware.preset_key
    try:
        hardware.set_preset_voltage(preset, original[0])
        hardware.set_preset_current(preset, original[1])
        hardware.save_preset(preset)
        hardware.preset_key = f"USER{preset}"
        hardware.apply_preset()
        assert hardware.get_voltage() == pytest.approx(original[0])
        assert hardware.get_current() == pytest.approx(original[1])
    finally:
        hardware.preset_key = key


def test_user_preset_protection_and_defaults(hardware, bench_config, pytestconfig):
    preset = pytestconfig.getoption("--hardware-preset")
    if preset is None:
        pytest.skip("preset edits require --hardware-preset")
    track_channels = bench_config.supported_channels("tracking")
    track = bool(track_channels)
    selected = (
        hardware.selected_channel if bench_config.supports("multi_channel") else None
    )
    if track:
        # Preset tracking applies to the tracking channels.
        hardware.selected_channel = track_channels[0]

    def snapshot():
        return {
            "voltage": hardware.get_preset_voltage(preset),
            "current": hardware.get_preset_current(preset),
            "ocp": hardware.get_preset_ocp(preset),
            "ovp": hardware.get_preset_ovp(preset),
            "otp": hardware.get_preset_otp_enabled(preset),
            "track": hardware.get_preset_tracking_enabled(preset) if track else None,
        }

    def restore(values):
        hardware.set_preset_voltage(preset, values["voltage"])
        hardware.set_preset_current(preset, values["current"])
        hardware.set_preset_ocp(preset, *values["ocp"])
        hardware.set_preset_ovp(preset, *values["ovp"])
        hardware.set_preset_otp_enabled(preset, values["otp"])
        if track:
            hardware.set_preset_tracking_enabled(preset, values["track"])

    original = snapshot()
    try:
        restore(original)  # Same-value writes of every preset setting.
        after = snapshot()
        for name in ("voltage", "current"):
            assert after[name] == pytest.approx(original[name])
        for name in ("ocp", "ovp"):
            assert after[name][0] is original[name][0]
            assert after[name][1] == pytest.approx(original[name][1])
        assert (after["otp"], after["track"]) == (original["otp"], original["track"])
        hardware.reset_preset(preset)
        defaults = snapshot()
        assert all(isinstance(defaults[name], float) for name in ("voltage", "current"))
    finally:
        restore(original)
        hardware.save_preset(preset)
        if selected is not None:
            hardware.selected_channel = selected
