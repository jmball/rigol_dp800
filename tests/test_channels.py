# SPDX-License-Identifier: GPL-3.0-or-later

"""Hardware-free coverage of physical channel views and discovery."""

import unittest
from unittest.mock import MagicMock

import pyvisa

from dp800 import DP800Channel, DP800
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

    def test_discovery_is_lazy_cached_and_exposes_only_physical_channels(self):
        for model, count in (
            ("DP831", 3),
            ("DP832", 3),
            ("DP821", 2),
            ("DP822", 2),
            ("DP811", 1),
            ("DP813", 1),
        ):
            for suffix in ("", "A"):
                with self.subTest(model=model + suffix):
                    self.supply.disconnect()
                    self.resource.commands.clear()
                    self.resource.responses["*IDN?"] = (
                        f"RIGOL,{model}{suffix},serial,version"
                    )
                    self.connect()
                    self.assertEqual(self.resource.commands, [":SYST:REM"])
                    self.assertEqual(self.supply.channel_count, count)
                    self.assertEqual(self.supply.channel_count, count)
                    self.assertEqual(
                        list(self.supply.channels), list(range(1, count + 1))
                    )
                    self.assertEqual(self.resource.commands.count("*IDN?"), 1)
                    with self.assertRaises(KeyError):
                        self.supply.channels[count + 1]

    def test_discovery_failure_does_not_cache_unknown_or_malformed_models(self):
        for identity in ("broken", "RIGOL,DP999,serial,version"):
            with self.subTest(identity=identity):
                self.resource.responses["*IDN?"] = identity
                with self.assertRaises(ValueError):
                    self.supply.channels
                self.assertIsNone(self.supply._channel_count)
        self.resource.responses["*IDN?"] = "RIGOL, DP832A ,serial,version"
        self.assertEqual(self.supply.channel_count, 3)

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

    def test_channel_uses_new_connection_and_rechecks_availability(self):
        channel1 = self.supply.channels[1]
        channel3 = self.supply.channels[3]
        self.supply.disconnect()
        for operation in (
            lambda: channel1.voltage,
            lambda: channel1.measure("ALL"),
            lambda: self.supply.channels,
            lambda: self.supply.channel_count,
        ):
            with self.assertRaisesRegex(RuntimeError, "not connected"):
                operation()
        replacement = FakeResource()
        replacement.responses["*IDN?"] = "RIGOL,DP811,serial,version"
        replacement.responses[":SOUR1:VOLT?"] = "3.3"
        self.manager.open_resource.return_value = replacement
        self.connect()
        self.assertEqual(replacement.commands, [":SYST:REM"])
        self.assertEqual(channel1.voltage, 3.3)
        self.assertIs(self.supply.channels[1], channel1)
        self.assertEqual(list(self.supply.channels), [1])
        with self.assertRaises(ValueError):
            channel3.voltage = 5.0
        self.assertNotIn(":SOUR3:VOLT 5.0", replacement.commands)
        self.supply.disconnect()
        replacement.responses["*IDN?"] = "RIGOL,DP832A,serial,version"
        self.connect()
        self.assertIs(self.supply.channels[3], channel3)
        channel3.voltage = 5.0
        self.assertEqual(replacement.commands[-1], ":SOUR3:VOLT 5.0")

    def test_discovery_and_channel_io_propagate_errors(self):
        error = OSError("Query failed")
        self.resource.query_error = error
        with self.assertRaises(OSError) as raised:
            self.supply.channels
        self.assertIs(raised.exception, error)
        self.assertIsNone(self.supply._channel_count)
        self.resource.query_error = None
        channel = self.supply.channels[1]
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
        self.assertEqual(virtual.channel_count, 3)
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


if __name__ == "__main__":
    unittest.main()
