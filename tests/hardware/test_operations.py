# SPDX-License-Identifier: GPL-3.0-or-later

"""Lifecycle and explicitly enabled trigger/reset/persistent operations."""

import pytest

pytestmark = pytest.mark.hardware


def test_disconnect_reconnect_and_channel_lifetime(
    hardware, bench_config, visa_manager
):
    channel = hardware.channels[bench_config.channels[0]]
    manager = visa_manager
    with pytest.raises(RuntimeError, match="Already connected"):
        hardware.connect(bench_config.resource_name, resource_manager=manager)
    try:
        hardware.disconnect()
    finally:
        assert hardware._instr is None
    hardware.disconnect()
    with pytest.raises(RuntimeError, match="not connected"):
        _ = channel.voltage
    hardware.connect(
        bench_config.resource_name,
        resource_manager=manager,
        timeout=bench_config.timeout,
        **bench_config.resource_options,
    )
    assert hardware.channels[channel.channel] is channel
    assert isinstance(channel.voltage, float)


@pytest.mark.parametrize(
    "exceptional", [False, True], ids=["normal-exit", "exceptional-exit"]
)
def test_context_manager_exit(hardware, exceptional):
    error = ValueError("test block exception")

    def use_context():
        with hardware as entered:
            assert entered is hardware
            if exceptional:
                raise error

    try:
        if exceptional:
            with pytest.raises(ValueError) as raised:
                use_context()
            assert raised.value is error
        else:
            use_context()
    finally:
        assert hardware._instr is None


def test_reset(hardware, bench_config):
    if not bench_config.reset:
        pytest.skip("reset requires --hardware-reset")
    hardware.reset()
    hardware.wait()
    assert hardware.get_opc() == 1
    assert hardware.get_errors() == []
    for number in bench_config.physical_channels:
        assert hardware.channels[number].output_enabled is False


def test_save_and_recall(hardware, bench_config):
    if bench_config.save_slot is None:
        pytest.skip("overwriting a setup requires --hardware-save-slot")
    channel = hardware.channels[bench_config.channels[0]]
    voltage, current = channel.voltage, channel.current
    try:
        channel.voltage = bench_config.channel_voltage(channel.channel)
        channel.current = bench_config.current
        hardware.save_setup(bench_config.save_slot)
        hardware.wait()
        channel.voltage = 0.0
        hardware.recall_setup(bench_config.save_slot)
        hardware.wait()
        assert channel.voltage == pytest.approx(
            bench_config.channel_voltage(channel.channel), abs=0.01
        )
        assert channel.current == pytest.approx(bench_config.current, abs=0.01)
        assert channel.output_enabled is False
    finally:
        channel.voltage, channel.current = voltage, current


def test_install_options(hardware, bench_config):
    if not bench_config.license:
        pytest.skip("option installation requires --hardware-license")
    if bench_config.model.endswith("A"):
        pytest.skip("A models include options at the factory")
    hardware.install_options(bench_config.license)
    assert hardware.get_errors() == []
    assert hardware.option_installation_status


def test_bus_trigger(hardware, bench_config):
    if not bench_config.trigger:
        pytest.skip("requires --hardware-trigger and installed trigger option")
    if not bench_config.allow_output:
        pytest.skip(
            "trigger setpoint verification also requires --hardware-allow-output"
        )
    number = bench_config.channels[0]
    channel = hardware.channels[number]
    selected = (
        hardware.selected_channel if len(bench_config.physical_channels) > 1 else None
    )
    coupling = hardware.trigger_coupling_channels if selected is not None else None
    settings = {}
    voltage, current = channel.voltage, channel.current
    sense = channel.sense_enabled if number in bench_config.sense_channels else None
    try:
        if selected is not None:
            hardware.selected_channel = number
            hardware.trigger_coupling_channels = "NONE"
        # These setup commands have no implemented public driver equivalent.
        for command in (
            ":TRIG:SOUR",
            ":TRIG:DEL",
            f":SOUR{number}:VOLT:TRIG",
            f":SOUR{number}:CURR:TRIG",
        ):
            settings[command] = hardware._query(f"{command}?")
        hardware._write(":TRIG:SOUR BUS")
        hardware._write(":TRIG:DEL 0")
        hardware._write(
            f":SOUR{number}:VOLT:TRIG {bench_config.channel_voltage(number)}"
        )
        hardware._write(f":SOUR{number}:CURR:TRIG {bench_config.current}")
        if sense is not None:
            channel.sense_enabled = False
        channel.voltage, channel.current = 0.0, bench_config.current
        channel.output_enabled = True
        hardware.init_trigger()
        hardware.trigger()
        hardware.wait()
        assert hardware.get_opc() == 1
        assert channel.voltage == pytest.approx(
            bench_config.channel_voltage(number), abs=0.01
        )
        assert channel.current == pytest.approx(bench_config.current, abs=0.01)
        assert channel.output_enabled is True
    finally:
        channel.output_enabled = False
        channel.voltage, channel.current = voltage, current
        if sense is not None:
            channel.sense_enabled = sense
        for command, value in settings.items():
            hardware._write(f"{command} {value}")
        if selected is not None:
            hardware.trigger_coupling_channels = (
                [item.split(":")[0] for item in coupling]
                if isinstance(coupling, list)
                else coupling
            )
            hardware.selected_channel = selected
