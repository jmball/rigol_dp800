# SPDX-License-Identifier: GPL-3.0-or-later

import warnings
from unittest.mock import MagicMock, patch
import pytest
import pyvisa
from dp800 import DP800, DP800Channel
from virtual_dp800 import DP800 as VirtualDP800
from tests.api import (
    ACTIONS,
    CHANNEL_READS,
    CHANNEL_WRITES,
    PLACEHOLDERS,
    READ_PROPERTIES,
    WRITE_PROPERTIES,
    placeholder_kwargs,
)


class TestVirtualDriver:

    def test_virtual_context_manager_disconnects_on_normal_and_exceptional_exit(self):
        for error in (None, ValueError("Block failed")):
            driver = VirtualDP800()

            def use_driver():
                with driver as entered:
                    assert entered is driver
                    driver.connect("virtual")
                    assert driver._connected
                    if error is not None:
                        raise error

            if error is None:
                use_driver()
            else:
                with pytest.raises(ValueError) as raised:
                    use_driver()
                assert raised.value is error
            assert not driver._connected

    def test_virtual_connection_never_opens_or_closes_manager(self):
        manager = MagicMock(spec=pyvisa.ResourceManager)
        driver = VirtualDP800()
        with patch.object(pyvisa, "ResourceManager") as factory:
            driver.connect("virtual", resource_manager=manager)
            with pytest.raises(RuntimeError):
                driver.connect("virtual")
            driver.disconnect()
            driver.disconnect()
            driver.connect("virtual")
            factory.assert_not_called()
        manager.open_resource.assert_not_called()
        manager.close.assert_not_called()

    def test_virtual_connection_warns_and_ignores_protocol_conflicts(self):
        for kwargs in (
            {"encoding": "utf-16"},
            {"read_termination": None},
            {"write_termination": "\r\n"},
        ):
            driver = VirtualDP800()
            with pytest.warns(UserWarning) as emitted:
                driver.connect("virtual", **kwargs)
            assert f"driver owns {next(iter(kwargs))}" in str(emitted[0].message)
            assert "will be ignored" in str(emitted[0].message)
            assert driver._connected
            driver.disconnect()
            with warnings.catch_warnings(record=True) as emitted_matching:
                warnings.simplefilter("always")
                driver.connect(
                    "virtual",
                    encoding="ascii",
                    read_termination="\n",
                    write_termination="\n",
                )
            assert emitted_matching == []

    def test_common_command_read_only_properties_and_virtual_placeholders(self):
        virtual = VirtualDP800()
        for driver in (DP800(), virtual):
            for name in (
                "identity",
                "status_byte_register",
                "option_installation_status",
            ):
                with pytest.raises(AttributeError):
                    setattr(driver, name, None)
        assert virtual.identity == "Virtual Rigol DP800"
        assert virtual.option_installation_status == [""]
        assert virtual.status_byte_register == 0
        for name in (
            "standard_event_enable_register",
            "status_byte_enable_register",
            "power_on_status_clear_bit",
        ):
            setattr(virtual, name, 1)
            assert getattr(virtual, name) == 0

    def test_virtual_channels_share_class_and_preserve_placeholders(self):
        virtual = VirtualDP800()
        assert list(virtual.channels) == [1, 2, 3]
        channel = virtual.channels[2]
        assert isinstance(channel, DP800Channel)
        channel.voltage = 5.0
        channel.current = 0.5
        channel.output_enabled = True
        assert channel.voltage == 0.0
        assert channel.current == 0.0
        assert not channel.output_enabled
        assert channel.measure("ALL") == 0.0
        assert channel.measured_voltage == 0.0
        assert channel.measured_current == 0.0
        assert channel.measured_power == 0.0
        virtual.connect("virtual")
        virtual.disconnect()
        virtual.connect("virtual")
        assert virtual.channels[2] is channel

    def test_virtual_output_and_protection_properties_preserve_placeholders(self):
        channel = VirtualDP800().channels[2]
        assert channel.output_mode == ""
        for name in ("sense_enabled", "ocp_enabled", "ovp_enabled"):
            setattr(channel, name, True)
            assert not getattr(channel, name)
        for name in ("ocp_value", "ovp_value"):
            for value in (1.0, "MIN", "MAX"):
                setattr(channel, name, value)
                assert getattr(channel, name) == 0.0
        assert not channel.ocp_tripped
        assert not channel.ovp_tripped
        channel.clear_ocp_label()
        channel.clear_ovp_label()

    def test_additional_virtual_properties_and_read_only_test_results(self):
        virtual = VirtualDP800()
        for name, value, expected in (
            ("delay_end_state", "LAST", ""),
            ("delay_groups", 12, 0),
            ("keylock_enabled", True, False),
            ("trigger_coupling_channels", ["CH1", "CH2"], ""),
            ("selected_channel", 2, 0),
        ):
            setattr(virtual, name, value)
            assert getattr(virtual, name) == expected
        assert virtual.self_test_results == []
        assert virtual.temperature_test_result == 0.0
        for driver in (DP800(), virtual):
            for name in ("self_test_results", "temperature_test_result"):
                with pytest.raises(AttributeError):
                    setattr(driver, name, None)


@pytest.mark.parametrize("name", PLACEHOLDERS)
def test_virtual_placeholders_are_noops(name):
    method = getattr(VirtualDP800(), name)
    assert method(**placeholder_kwargs(method)) is None


VIRTUAL_READS = {
    "delay_end_state": "",
    "delay_groups": 0,
    "get_apply": 0.0,
    "get_current": 0.0,
    "get_delay_cycles": "",
    "get_errors": [],
    "get_ocp": False,
    "get_ocp_enable": False,
    "get_ocp_value": 0.0,
    "get_opc": 0,
    "get_output_enable": False,
    "get_output_mode": "",
    "get_output_sense_enable": False,
    "get_ovp": False,
    "get_ovp_enable": False,
    "get_ovp_value": 0.0,
    "get_standard_event_register": 0,
    "get_voltage": 0.0,
    "identity": "Virtual Rigol DP800",
    "keylock_enabled": False,
    "measure": 0.0,
    "option_installation_status": [""],
    "power_on_status_clear_bit": 0,
    "selected_channel": 0,
    "self_test_results": [],
    "standard_event_enable_register": 0,
    "status_byte_enable_register": 0,
    "status_byte_register": 0,
    "temperature_test_result": 0.0,
    "trigger_coupling_channels": "",
}


@pytest.mark.parametrize("name,expected", VIRTUAL_READS.items())
def test_virtual_read_interface(name, expected):
    driver = VirtualDP800()
    member = getattr(driver, name)
    result = member() if callable(member) else member
    assert result == expected
    assert type(result) is type(expected)


@pytest.mark.parametrize("name", WRITE_PROPERTIES)
def test_virtual_property_setters_preserve_placeholders(name):
    driver = VirtualDP800()
    setattr(driver, name, WRITE_PROPERTIES[name][0])
    assert getattr(driver, name) == VIRTUAL_READS[name]


@pytest.mark.parametrize("name", CHANNEL_WRITES)
def test_virtual_channel_setters_preserve_placeholders(name):
    driver = VirtualDP800()
    getattr(driver, name)(CHANNEL_WRITES[name][0], channel=2)
    getter = name.replace("set_", "get_", 1)
    result = getattr(driver, getter)(channel=2)
    assert result == VIRTUAL_READS[getter]
    assert type(result) is type(VIRTUAL_READS[getter])


def test_virtual_read_inventory_matches_driver_interface():
    assert set(VIRTUAL_READS) == set(READ_PROPERTIES) | set(CHANNEL_READS) | {
        "get_apply",
        "get_delay_cycles",
        "get_standard_event_register",
        "get_opc",
        "measure",
        "get_errors",
    }


@pytest.mark.parametrize("name", ACTIONS)
def test_virtual_action_interface(name):
    args, _ = ACTIONS[name]
    assert getattr(VirtualDP800(), name)(*args) is None


def test_virtual_apply_and_delay_setters_remain_noops():
    driver = VirtualDP800()
    driver.set_apply(channel=2, voltage=1.2, current=0.1)
    driver.set_delay_cycles("N", 3)
    assert driver.get_apply() == 0.0
    assert driver.get_delay_cycles() == ""
