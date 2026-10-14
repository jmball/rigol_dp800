# SPDX-License-Identifier: GPL-3.0-or-later

"""Hardware-free coverage of channel views and instrument error propagation."""

import unittest
from unittest.mock import MagicMock

import pyvisa

from dp800 import DP800Channel, DP800, InstrumentError
from virtual_dp800 import DP800 as VirtualDP800

from test_driver import FakeResource


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.supply = DP800()
        self.resource = FakeResource()
        self.manager = MagicMock(spec=pyvisa.ResourceManager)
        self.manager.open_resource.return_value = self.resource
        self.connect()

    def connect(self):
        self.supply.connect("TCPIP::example::INSTR", resource_manager=self.manager)

    def test_channel_views_are_always_one_to_three_without_identity_queries(self):
        self.assertEqual(list(self.supply.channels), [1, 2, 3])
        self.assertEqual(self.resource.commands, [":SYST:REM"])
        self.supply.disconnect()
        before = list(self.resource.io_events)
        self.assertEqual(list(self.supply.channels), [1, 2, 3])
        self.assertEqual(self.resource.io_events, before)
        self.assertFalse(hasattr(self.supply, "channel_count"))
        with self.assertRaises(KeyError):
            self.supply.channels[4]

    def test_channels_do_not_depend_on_identity_or_model(self):
        self.resource.responses["*IDN?"] = "unrecognized instrument"
        self.assertEqual(list(self.supply.channels), [1, 2, 3])
        self.assertNotIn("*IDN?", self.resource.commands)

    def test_channel_objects_and_numbers_are_stable_and_read_only(self):
        channel = self.supply.channels[2]
        self.assertIsInstance(channel, DP800Channel)
        self.assertIs(self.supply.channels[2], channel)
        self.assertEqual(channel.channel, 2)
        with self.assertRaises(AttributeError):
            channel.channel = 1
        with self.assertRaises(TypeError):
            self.supply.channels[1] = channel
        for invalid in (0, -1, 4):
            with self.assertRaises(ValueError):
                DP800Channel(self.supply, invalid)
        for invalid in (True, 1.0, "1"):
            with self.assertRaises(TypeError):
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
        self.assertEqual(channel.voltage, 5.0)
        self.assertEqual(channel.current, 0.5)
        self.assertTrue(channel.output_enabled)
        self.resource.responses[":OUTP? CH2"] = "OFF"
        channel.output_enabled = False
        self.assertFalse(channel.output_enabled)
        self.assertEqual(
            self.resource.commands,
            [
                ":SOUR2:VOLT 5.0",
                ":SOUR2:CURR 0.5",
                ":OUTP  CH2,ON",
                ":SOUR2:VOLT?",
                ":SOUR2:CURR?",
                ":OUTP? CH2",
                ":OUTP  CH2,OFF",
                ":OUTP? CH2",
            ],
        )

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
            with self.subTest(property=name):
                self.assertEqual(getattr(channel, name), expected)
                self.assertEqual(self.resource.commands[-1], f":MEAS:{func}? CH2")
                with self.assertRaises(AttributeError):
                    setattr(channel, name, 0.0)
        self.assertEqual(channel.measure(), "4.9")
        self.assertEqual(self.resource.commands[-1], ":MEAS? CH2")
        self.assertEqual(channel.measure("ALL"), ["4.9", "0.4", "1.96"])
        self.assertEqual(self.resource.commands[-1], ":MEAS:ALL? CH2")
        for func in ("VOLT", "CURR", "POWE"):
            self.assertIsInstance(channel.measure(func), str)
        self.resource.responses[":MEAS:VOLT? CH2"] = "bad"
        with self.assertRaises(ValueError):
            channel.measured_voltage
        self.resource.responses[":MEAS:VOLT? CH2"] = "1,2"
        with self.assertRaisesRegex(ValueError, "Expected one measurement"):
            channel.measured_voltage

    def test_channel_survives_reconnection_and_device_checks_availability(self):
        channel1 = self.supply.channels[1]
        channel3 = self.supply.channels[3]
        self.supply.disconnect()
        for operation in (lambda: channel1.voltage, lambda: channel1.measure("ALL")):
            with self.assertRaisesRegex(RuntimeError, "not connected"):
                operation()
        replacement = FakeResource()
        replacement.responses["*IDN?"] = "RIGOL,DP811,serial,version"
        replacement.responses[":SOUR1:VOLT?"] = "3.3"
        replacement.errors_after_write[":SOUR3:VOLT 5.0"] = ['-222,"Invalid channel"']
        self.manager.open_resource.return_value = replacement
        self.connect()
        self.assertEqual(channel1.voltage, 3.3)
        self.assertIs(self.supply.channels[1], channel1)
        self.assertIs(self.supply.channels[3], channel3)
        with self.assertRaises(InstrumentError) as raised:
            channel3.voltage = 5.0
        self.assertEqual(str(raised.exception), '-222,"Invalid channel"')
        self.assertIn(":SOUR3:VOLT 5.0", replacement.commands)
        self.assertNotIn("*IDN?", replacement.commands)

    def test_channel_io_propagates_transport_errors(self):
        channel = self.supply.channels[1]
        error = OSError("Write failed")
        self.resource.write_errors[":SOUR1:VOLT 5.0"] = error
        with self.assertRaises(OSError) as raised:
            channel.voltage = 5.0
        self.assertIs(raised.exception, error)
        self.resource.query_error = error
        with self.assertRaises(OSError) as raised:
            channel.measured_voltage
        self.assertIs(raised.exception, error)

    def test_virtual_channels_share_class_and_preserve_placeholders(self):
        virtual = VirtualDP800()
        self.assertEqual(list(virtual.channels), [1, 2, 3])
        channel = virtual.channels[2]
        self.assertIsInstance(channel, DP800Channel)
        channel.voltage = 5.0
        channel.current = 0.5
        channel.output_enabled = True
        self.assertEqual(channel.voltage, 0.0)
        self.assertEqual(channel.current, 0.0)
        self.assertFalse(channel.output_enabled)
        self.assertEqual(channel.measure("ALL"), 0.0)
        self.assertEqual(channel.measured_voltage, 0.0)
        self.assertEqual(channel.measured_current, 0.0)
        self.assertEqual(channel.measured_power, 0.0)
        virtual.connect("virtual")
        virtual.disconnect()
        virtual.connect("virtual")
        self.assertIs(virtual.channels[2], channel)

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
                with self.subTest(property=name, response=response):
                    self.resource.responses[command] = response
                    self.assertEqual(getattr(channel, name), expected)
                    self.assertEqual(getattr(channel, name), expected)
                    self.assertEqual(self.resource.commands[-2:], [command, command])
                    error = OSError("Query failed")
                    self.resource.query_error = error
                    with self.assertRaises(OSError) as raised:
                        getattr(channel, name)
                    self.assertIs(raised.exception, error)
                    self.resource.query_error = None
        for name in ("output_mode", "ocp_tripped", "ovp_tripped"):
            with self.assertRaises(AttributeError):
                setattr(channel, name, None)
        self.assertFalse(
            any(command.startswith(":INST") for command in self.resource.commands)
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
                with self.subTest(property=name, value=value):
                    command = prefix + suffix
                    setattr(channel, name, value)
                    self.assertEqual(self.resource.commands[-1], command)
                    error = OSError("Write failed")
                    self.resource.write_errors[command] = error
                    with self.assertRaises(OSError) as raised:
                        setattr(channel, name, value)
                    self.assertIs(raised.exception, error)
                    self.resource.write_errors.clear()
        for name, command in (
            ("clear_ocp_label", ":OUTP:OCP:CLEAR CH2"),
            ("clear_ovp_label", ":OUTP:OVP:CLEAR CH2"),
        ):
            with self.subTest(method=name):
                getattr(channel, name)()
                self.assertEqual(self.resource.commands[-1], command)
                error = OSError("Clear failed")
                self.resource.write_errors[command] = error
                with self.assertRaises(OSError) as raised:
                    getattr(channel, name)()
                self.assertIs(raised.exception, error)
                self.resource.write_errors.clear()
        self.assertEqual(self.resource.commands.count("*IDN?"), 0)
        self.assertFalse(
            any(command.startswith(":INST") for command in self.resource.commands)
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
            with self.assertRaises(RuntimeError):
                getattr(channel, name)
        for name, value in setters:
            with self.assertRaises(RuntimeError):
                setattr(channel, name, value)
        for name in actions:
            with self.assertRaises(RuntimeError):
                getattr(channel, name)()
        self.assertEqual(self.resource.commands, [])

    def test_virtual_output_and_protection_properties_preserve_placeholders(self):
        channel = VirtualDP800().channels[2]
        self.assertEqual(channel.output_mode, "")
        for name in ("sense_enabled", "ocp_enabled", "ovp_enabled"):
            setattr(channel, name, True)
            self.assertFalse(getattr(channel, name))
        for name in ("ocp_value", "ovp_value"):
            for value in (1.0, "MIN", "MAX"):
                setattr(channel, name, value)
                self.assertEqual(getattr(channel, name), 0.0)
        self.assertFalse(channel.ocp_tripped)
        self.assertFalse(channel.ovp_tripped)
        channel.clear_ocp_label()
        channel.clear_ovp_label()


if __name__ == "__main__":
    unittest.main()
