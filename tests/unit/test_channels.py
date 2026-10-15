# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from dp800 import DP800Channel, InstrumentError
from tests.fakes import FakeResource


class TestChannel:

    @pytest.fixture(autouse=True)
    def setup(self, fake_visa, caplog):
        self.supply, self.resource, self.manager = fake_visa
        self.caplog = caplog
        self.connect()

    def connect(self):
        self.supply.connect("TCPIP::example::INSTR", resource_manager=self.manager)

    def test_channel_views_are_always_one_to_three_without_identity_queries(self):
        assert list(self.supply.channels) == [1, 2, 3]
        assert self.resource.commands == []
        self.supply.disconnect()
        before = list(self.resource.io_events)
        assert list(self.supply.channels) == [1, 2, 3]
        assert self.resource.io_events == before
        assert not hasattr(self.supply, "channel_count")
        with pytest.raises(KeyError):
            self.supply.channels[4]

    def test_channel_objects_and_numbers_are_stable_and_read_only(self):
        channel = self.supply.channels[2]
        assert isinstance(channel, DP800Channel)
        assert self.supply.channels[2] is channel
        assert channel.channel == 2
        with pytest.raises(AttributeError):
            channel.channel = 1
        with pytest.raises(TypeError):
            self.supply.channels[1] = channel
        for invalid in (0, -1, 4):
            with pytest.raises(ValueError):
                DP800Channel(self.supply, invalid)
        for invalid in (True, 1.0, "1"):
            with pytest.raises(TypeError):
                DP800Channel(self.supply, invalid)

    def test_setpoints_and_output_address_fixed_channel_without_selecting_it(self):
        channel = self.supply.channels[2]
        self.resource.commands.clear()
        self.resource.responses.update(
            {":SOUR2:VOLT?": "5.0", ":SOUR2:CURR?": "0.5", ":OUTP? CH2": "ON"}
        )
        channel.voltage = 5.0
        channel.current = 0.5
        channel.output_enabled = True
        assert channel.voltage == 5.0
        assert channel.current == 0.5
        assert channel.output_enabled
        self.resource.responses[":OUTP? CH2"] = "OFF"
        channel.output_enabled = False
        assert not channel.output_enabled
        assert self.resource.commands == [
            ":SOUR2:VOLT 5.0",
            ":SOUR2:CURR 0.5",
            ":OUTP  CH2,ON",
            ":SOUR2:VOLT?",
            ":SOUR2:CURR?",
            ":OUTP? CH2",
            ":OUTP  CH2,OFF",
            ":OUTP? CH2",
        ]

    def test_measurement_properties_convert_to_floats_and_measure_keeps_all(self):
        channel = self.supply.channels[2]
        self.resource.responses.update(
            {
                ":MEAS? CH2": "4.9",
                ":MEAS:VOLT? CH2": "4.9",
                ":MEAS:CURR? CH2": "0.4",
                ":MEAS:POWE? CH2": "1.96",
                ":MEAS:ALL? CH2": "4.9,0.4,1.96",
            }
        )
        for name, func, expected in (
            ("measured_voltage", "VOLT", 4.9),
            ("measured_current", "CURR", 0.4),
            ("measured_power", "POWE", 1.96),
        ):
            assert getattr(channel, name) == expected
            assert self.resource.commands[-1] == f":MEAS:{func}? CH2"
            with pytest.raises(AttributeError):
                setattr(channel, name, 0.0)
        assert channel.measure() == "4.9"
        assert self.resource.commands[-1] == ":MEAS? CH2"
        assert channel.measure("ALL") == ["4.9", "0.4", "1.96"]
        assert self.resource.commands[-1] == ":MEAS:ALL? CH2"
        for func in ("VOLT", "CURR", "POWE"):
            assert isinstance(channel.measure(func), str)
        self.resource.responses[":MEAS:VOLT? CH2"] = "bad"
        with pytest.raises(ValueError):
            channel.measured_voltage
        self.resource.responses[":MEAS:VOLT? CH2"] = "1,2"
        with pytest.raises(ValueError, match="Expected one measurement"):
            channel.measured_voltage

    def test_channel_survives_reconnection_and_device_checks_availability(self):
        channel1 = self.supply.channels[1]
        channel3 = self.supply.channels[3]
        self.supply.disconnect()
        for operation in (lambda: channel1.voltage, lambda: channel1.measure("ALL")):
            with pytest.raises(RuntimeError, match="not connected"):
                operation()
        replacement = FakeResource()
        replacement.responses["*IDN?"] = "RIGOL,DP811,serial,version"
        replacement.responses[":SOUR1:VOLT?"] = "3.3"
        replacement.errors_after_write[":SOUR3:VOLT 5.0"] = ['-222,"Invalid channel"']
        self.manager.open_resource.return_value = replacement
        self.connect()
        assert channel1.voltage == 3.3
        assert self.supply.channels[1] is channel1
        assert self.supply.channels[3] is channel3
        with pytest.raises(InstrumentError) as raised:
            channel3.voltage = 5.0
        assert str(raised.value) == '-222,"Invalid channel"'
        assert ":SOUR3:VOLT 5.0" in replacement.commands
        assert "*IDN?" not in replacement.commands

    def test_channel_io_propagates_transport_errors(self):
        channel = self.supply.channels[1]
        error = OSError("Write failed")
        self.resource.write_errors[":SOUR1:VOLT 5.0"] = error
        with pytest.raises(OSError) as raised:
            channel.voltage = 5.0
        assert raised.value is error
        self.resource.query_error = error
        with pytest.raises(OSError) as raised:
            channel.measured_voltage
        assert raised.value is error

    def test_output_and_protection_properties_query_the_fixed_channel(self):
        channel = self.supply.channels[2]
        for name, command, responses in (
            (
                "output_mode",
                ":OUTP:MODE? CH2",
                (("CV", "CV"), ("CC", "CC"), ("UR", "UR")),
            ),
            ("sense_enabled", ":OUTP:SENS? CH2", (("ON", True), ("OFF", False))),
            ("ocp_enabled", ":OUTP:OCP? CH2", (("ON", True), ("OFF", False))),
            ("ocp_value", ":OUTP:OCP:VAL? CH2", (("0.75", 0.75),)),
            ("ocp_tripped", ":OUTP:OCP:ALAR? CH2", (("YES", True), ("NO", False))),
            ("ovp_enabled", ":OUTP:OVP? CH2", (("ON", True), ("OFF", False))),
            ("ovp_value", ":OUTP:OVP:VAL? CH2", (("5.5", 5.5),)),
            ("ovp_tripped", ":OUTP:OVP:ALAR? CH2", (("YES", True), ("NO", False))),
        ):
            for response, expected in responses:
                self.resource.responses[command] = response
                assert getattr(channel, name) == expected
                assert getattr(channel, name) == expected
                assert self.resource.commands[-2:] == [command, command]
                error = OSError("Query failed")
                self.resource.query_error = error
                with pytest.raises(OSError) as raised:
                    getattr(channel, name)
                assert raised.value is error
                self.resource.query_error = None
        for name in ("output_mode", "ocp_tripped", "ovp_tripped"):
            with pytest.raises(AttributeError):
                setattr(channel, name, None)
        assert not any(
            (command.startswith(":INST") for command in self.resource.commands)
        )

    def test_protection_and_sensing_assignments_and_alarm_clearing(self):
        channel = self.supply.channels[2]
        for name, prefix, values in (
            ("sense_enabled", ":OUTP:SENS CH2,", ((True, "ON"), (False, "OFF"))),
            ("ocp_enabled", ":OUTP:OCP CH2,", ((True, "ON"), (False, "OFF"))),
            (
                "ocp_value",
                ":OUTP:OCP:VAL CH2,",
                ((0.75, "0.75"), ("MIN", "MIN"), ("MAX", "MAX")),
            ),
            ("ovp_enabled", ":OUTP:OVP CH2,", ((True, "ON"), (False, "OFF"))),
            (
                "ovp_value",
                ":OUTP:OVP:VAL CH2,",
                ((5.5, "5.5"), ("MIN", "MIN"), ("MAX", "MAX")),
            ),
        ):
            for value, suffix in values:
                command = prefix + suffix
                setattr(channel, name, value)
                assert self.resource.commands[-1] == command
                error = OSError("Write failed")
                self.resource.write_errors[command] = error
                with pytest.raises(OSError) as raised:
                    setattr(channel, name, value)
                assert raised.value is error
                self.resource.write_errors.clear()
        for name, command in (
            ("clear_ocp_label", ":OUTP:OCP:CLEAR CH2"),
            ("clear_ovp_label", ":OUTP:OVP:CLEAR CH2"),
        ):
            getattr(channel, name)()
            assert self.resource.commands[-1] == command
            error = OSError("Clear failed")
            self.resource.write_errors[command] = error
            with pytest.raises(OSError) as raised:
                getattr(channel, name)()
            assert raised.value is error
            self.resource.write_errors.clear()
        assert self.resource.commands.count("*IDN?") == 0
        assert not any(
            (command.startswith(":INST") for command in self.resource.commands)
        )

    def test_new_channel_operations_fail_while_disconnected(self):
        channel = self.supply.channels[3]
        getters = (
            "output_mode",
            "sense_enabled",
            "ocp_enabled",
            "ocp_value",
            "ocp_tripped",
            "ovp_enabled",
            "ovp_value",
            "ovp_tripped",
        )
        setters = (
            ("sense_enabled", True),
            ("ocp_enabled", True),
            ("ocp_value", 0.75),
            ("ovp_enabled", True),
            ("ovp_value", 5.5),
        )
        actions = ("clear_ocp_label", "clear_ovp_label")
        self.supply.disconnect()
        self.resource.commands.clear()
        for name in getters:
            with pytest.raises(RuntimeError):
                getattr(channel, name)
        for name, value in setters:
            with pytest.raises(RuntimeError):
                setattr(channel, name, value)
        for name in actions:
            with pytest.raises(RuntimeError):
                getattr(channel, name)()
        assert self.resource.commands == []
