# SPDX-License-Identifier: GPL-3.0-or-later

"""Validate hardware configuration and cleanup without opening a real device."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from tests.hardware import conftest as hardware_fixtures
from tests.hardware.support import HardwareConfig


def options(**overrides):
    values = {
        "--visa-resource": "TCPIP::example::INSTR",
        "--hardware-model": "DP832",
        "--hardware-channels": None,
        "--hardware-voltage": 1.0,
        "--hardware-current": 0.01,
        "--visa-timeout": 5000,
        "--visa-backend": None,
        "--visa-options": "{}",
        "--hardware-allow-output": False,
        "--hardware-trigger": False,
        "--hardware-reset": False,
        "--hardware-save-slot": None,
        "--hardware-license": None,
    }
    values.update(overrides)
    return Mock(getoption=values.__getitem__)


@pytest.mark.parametrize(
    "model,count,sense",
    [
        ("DP811", 1, (1,)),
        ("DP813A", 1, (1,)),
        ("DP821A", 2, (2,)),
        ("DP822", 2, (2,)),
        ("DP831", 3, ()),
        ("DP832A", 3, ()),
    ],
)
def test_model_applicability(model, count, sense):
    config = HardwareConfig.from_pytest(options(**{"--hardware-model": model}))
    assert config.channels == config.physical_channels == tuple(range(1, count + 1))
    assert config.sense_channels == sense
    assert config.allow_output is config.trigger is config.reset is False


def test_explicit_configuration_and_negative_channel():
    config = HardwareConfig.from_pytest(
        options(
            **{
                "--hardware-model": "dp831a",
                "--hardware-channels": "3,1",
                "--visa-backend": "@py",
                "--visa-timeout": 7000,
                "--visa-options": '{"baud_rate": 19200, "open_timeout": 1000}',
                "--hardware-voltage": 2.0,
                "--hardware-current": 0.02,
                "--hardware-allow-output": True,
                "--hardware-trigger": True,
                "--hardware-reset": True,
                "--hardware-save-slot": 4,
                "--hardware-license": "A" * 28,
            }
        )
    )
    assert config.model == "DP831A" and config.channels == (3, 1)
    assert config.channel_voltage(3) == -2.0
    assert config.channel_voltage(1) == 2.0
    assert config.backend == "@py" and config.timeout == 7000
    assert config.resource_options == {"baud_rate": 19200, "open_timeout": 1000}
    assert config.current == 0.02
    assert config.allow_output and config.trigger and config.reset
    assert config.save_slot == 4 and config.license == "A" * 28


def test_hardware_disabled_without_resource():
    assert HardwareConfig.from_pytest(options(**{"--visa-resource": None})) is None


@pytest.mark.parametrize(
    "option,value",
    [
        ("--hardware-model", None),
        ("--hardware-model", "DP999"),
        ("--hardware-channels", "1,1"),
        ("--hardware-channels", "4"),
        ("--hardware-channels", "zero"),
        ("--hardware-channels", "1,"),
        ("--hardware-voltage", 0),
        ("--hardware-voltage", 5.1),
        ("--hardware-voltage", float("nan")),
        ("--hardware-voltage", float("inf")),
        ("--hardware-current", -1),
        ("--hardware-current", 0.11),
        ("--hardware-current", float("nan")),
        ("--visa-timeout", 0),
        ("--hardware-save-slot", 0),
        ("--hardware-save-slot", 10),
        ("--hardware-license", "invalid"),
        ("--hardware-license", "é" * 28),
        ("--visa-options", "invalid"),
        ("--visa-options", "[]"),
        ("--visa-options", '{"timeout": 1000}'),
        ("--visa-options", '{"resource_manager": "@py"}'),
    ],
)
def test_invalid_hardware_options_fail_before_io(option, value):
    with pytest.raises(pytest.UsageError, match=option):
        HardwareConfig.from_pytest(options(**{option: value}))


def test_channel_subset_respects_model():
    with pytest.raises(pytest.UsageError, match="physical channels"):
        HardwareConfig.from_pytest(
            options(**{"--hardware-model": "DP811", "--hardware-channels": "2"})
        )


@pytest.mark.parametrize("model", ["DP811", "DP832"])
def test_harness_cleanup_only_addresses_physical_channels(
    fake_visa, monkeypatch, model
):
    driver, resource, manager = fake_visa
    resource.responses["*IDN?"] = f"RIGOL,{model},serial,version"
    config = HardwareConfig.from_pytest(options(**{"--hardware-model": model}))
    monkeypatch.setattr(hardware_fixtures, "DP800", lambda: driver)
    generator = hardware_fixtures.hardware.__wrapped__(config, manager)
    # Fixture construction itself performs no I/O.
    manager.open_resource.assert_not_called()
    assert next(generator) is driver
    resource.commands.clear()
    with pytest.raises(StopIteration):
        next(generator)
    assert resource.commands == [
        f":OUTP  CH{number},OFF" for number in config.physical_channels
    ] + [":SYST:KLOC:STAT OFF", ":SYST:LOC"]
    assert driver._instr is None and resource.closed == 1
    # Its own fixture retains responsibility for closing the manager.
    manager.close.assert_not_called()


def test_harness_checks_identity_before_changing_outputs(fake_visa, monkeypatch):
    driver, resource, manager = fake_visa
    config = HardwareConfig.from_pytest(options(**{"--hardware-model": "DP811"}))
    monkeypatch.setattr(hardware_fixtures, "DP800", lambda: driver)
    generator = hardware_fixtures.hardware.__wrapped__(config, manager)
    with pytest.raises(AssertionError, match="Connected model"):
        next(generator)
    assert resource.commands == ["*IDN?"]
    assert resource.closed == 1 and driver._instr is None


def test_harness_attempts_remaining_cleanup_after_failure(fake_visa, monkeypatch):
    driver, resource, manager = fake_visa
    config = HardwareConfig.from_pytest(options())
    monkeypatch.setattr(hardware_fixtures, "DP800", lambda: driver)
    generator = hardware_fixtures.hardware.__wrapped__(config, manager)
    next(generator)
    failure = OSError("CH1 shutdown failed")
    resource.write_errors[":OUTP  CH1,OFF"] = failure
    resource.commands.clear()
    with pytest.raises(OSError) as raised:
        next(generator)
    assert raised.value is failure
    assert ":OUTP  CH3,OFF" in resource.commands and ":SYST:LOC" in resource.commands
    assert resource.closed == 1 and driver._instr is None


@pytest.mark.parametrize("backend", [None, "@py"])
def test_harness_manager_is_closed_on_failure(fake_visa, monkeypatch, backend):
    _, _, manager = fake_visa
    config = replace(HardwareConfig.from_pytest(options()), backend=backend)
    factory = Mock(return_value=manager)
    monkeypatch.setattr(hardware_fixtures.pyvisa, "ResourceManager", factory)
    generator = hardware_fixtures.visa_manager.__wrapped__(config)
    assert next(generator) is manager
    factory.assert_called_once_with(*([backend] if backend else []))
    with pytest.raises(OSError, match="test failure"):
        generator.throw(OSError("test failure"))
    manager.close.assert_called_once_with()
