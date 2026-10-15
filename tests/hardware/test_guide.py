# SPDX-License-Identifier: GPL-3.0-or-later

"""Extended round trips on a bench with the relevant options installed.

--hardware-guide enables this module. File/preset writes additionally require a
scratch slot/directory/preset. Communication changes and key locking are covered
with fakes and the virtual supply, as they can interrupt the active test session.
"""

import time

import pytest

from tests.extended_api import PROPERTIES

pytestmark = pytest.mark.hardware


@pytest.fixture(autouse=True)
def require_extended_suite(pytestconfig):
    if not pytestconfig.getoption("--hardware-guide"):
        pytest.skip("extended guide cases require --hardware-guide")


# Reads and same-value assignments exercise the new settings without starting
# timed outputs, changing communication addresses or locking out the connection.
ROUND_TRIP_PROPERTIES = [
    name
    for name, case in PROPERTIES.items()
    if case[4]
    and not name.startswith(("analyzer_", "lan_", "rs232_", "monitor_"))
    and name
    not in {
        "gpib_address",
        "output_range",
        "locked",
        "language",
        "beeper_enabled",
        "otp_enabled",
        "on_off_sync_enabled",
        "recorder_enabled",
        "recorder_period",
        "directory",
        "delay_enabled",
        "timer_enabled",
        "trigger_source",
        "trigger_delay",
    }
]


@pytest.mark.parametrize("name", ROUND_TRIP_PROPERTIES)
def test_extended_property_round_trip(hardware, name):
    original = getattr(hardware, name)
    setattr(hardware, name, original)
    actual = getattr(hardware, name)
    assert (
        actual == pytest.approx(original)
        if isinstance(original, (int, float))
        else actual == original
    )


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


def test_recording_and_analyzer(hardware, bench_config):
    if bench_config.save_slot is None:
        pytest.skip("recording overwrites ROF data in --hardware-save-slot")
    hardware.set_recorder_destination(bench_config.save_slot, "DP8TEST.ROF")
    period = hardware.recorder_period
    try:
        hardware.recorder_period = 1
        hardware.recorder_enabled = True
        time.sleep(2.1)  # Produce real samples; not an error-query delay.
    finally:
        hardware.recorder_enabled = False
        hardware.recorder_period = period
    hardware.open_recording(bench_config.save_slot)
    hardware.analyze()
    assert hardware.analyzer_results["Group"] >= 1
    values = hardware.get_recorded_values(hardware.analyzer_start_time)
    assert len(values) == 3


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
