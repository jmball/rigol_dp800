# SPDX-License-Identifier: GPL-3.0-or-later

"""Hardware-free regression tests for connection ownership and driver responses."""

import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import pyvisa
from pyvisa.resources import MessageBasedResource, Resource

from dp800 import dp800
from virtual_dp800 import dp800 as VirtualDP800


class FakeResource(MessageBasedResource):
    """Exercise attribute configuration and I/O without a VISA backend."""

    encoding = "utf-8"
    read_termination = None
    write_termination = "\r\n"
    timeout = 2000
    query_delay = 0.0

    def __init__(self):
        self._session = None
        self.commands = []
        self.responses = {"*IDN?": "RIGOL,DP832,serial,version"}
        self.write_errors = {}
        self.query_error = None
        self.close_error = None
        self.fail_setting = None
        self.closed = 0
        self.on_io = lambda: None

    def __setattr__(self, name, value):
        if name == getattr(self, "fail_setting", None):
            raise ValueError("Configuration failed")
        object.__setattr__(self, name, value)

    def write(self, command):
        self.on_io()
        self.commands.append(command)
        if command in self.write_errors:
            raise self.write_errors[command]
        return len(command)

    def query(self, command):
        self.on_io()
        self.commands.append(command)
        if self.query_error is not None:
            raise self.query_error
        return self.responses[command]

    def close(self):
        self.closed += 1
        if self.close_error is not None:
            raise self.close_error


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.driver = dp800()
        self.resource = FakeResource()
        self.manager = MagicMock(spec=pyvisa.ResourceManager)
        self.manager.open_resource.return_value = self.resource

    def connect(self, **kwargs):
        self.driver.connect(
            "TCPIP::example::INSTR", resource_manager=self.manager, **kwargs
        )

    def test_import_does_not_create_resource_manager(self):
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from unittest.mock import patch; "
                "import pyvisa; "
                "p = patch.object(pyvisa, 'ResourceManager'); m = p.start(); "
                "import dp800; import virtual_dp800; m.assert_not_called()",
            ],
            check=True,
        )

    def test_configuration_precedes_io_and_publication_without_reset(self):
        def check_initialization():
            self.assertIsNone(self.driver.instr)
            self.assertEqual(self.resource.encoding, "ascii")
            self.assertEqual(self.resource.read_termination, "\n")
            self.assertEqual(self.resource.write_termination, "\n")
            self.assertEqual(self.resource.timeout, 500)

        self.resource.on_io = check_initialization
        self.connect(timeout=500, query_delay=0.1, open_timeout=250)
        self.manager.open_resource.assert_called_once_with(
            "TCPIP::example::INSTR", open_timeout=250
        )
        self.assertEqual(self.resource.commands, [":SYST:REM", "*IDN?"])
        self.assertEqual(self.resource.query_delay, 0.1)
        self.assertIs(self.driver.instr, self.resource)
        self.assertIs(self.driver._resource_manager, self.manager)

    def test_matching_protocol_values_are_accepted(self):
        self.connect(encoding="ascii", read_termination="\n", write_termination="\n")
        self.assertIs(self.driver.instr, self.resource)

    def test_protocol_conflicts_are_rejected_before_open(self):
        for kwargs in (
            {"encoding": "utf-16"},
            {"read_termination": None},
            {"write_termination": "\r\n"},
        ):
            with (
                self.subTest(kwargs=kwargs),
                patch.object(pyvisa, "ResourceManager") as factory,
            ):
                with self.assertRaises(ValueError):
                    self.driver.connect("TCPIP::example::INSTR", **kwargs)
                factory.assert_not_called()
                self.manager.open_resource.assert_not_called()
                self.assertIsNone(self.driver.instr)

    def test_connecting_twice_raises_without_touching_existing_connection(self):
        self.connect()
        with self.assertRaises(RuntimeError):
            self.connect()
        self.manager.open_resource.assert_called_once()
        self.assertEqual(self.resource.closed, 0)
        self.assertIs(self.driver.instr, self.resource)

    def test_disconnect_is_idempotent_and_caller_manager_remains_open(self):
        self.driver.disconnect()
        self.connect()
        self.driver.disconnect()
        self.driver.disconnect()
        self.assertEqual(
            self.resource.commands[2:],
            [
                ":OUTP  CH1,OFF",
                ":OUTP  CH2,OFF",
                ":OUTP  CH3,OFF",
                ":SYST:LOC",
            ],
        )
        self.assertEqual(self.resource.closed, 1)
        self.assertIsNone(self.driver.instr)
        self.assertIsNone(self.driver._resource_manager)
        self.manager.close.assert_not_called()

    def test_reconnect_after_disconnect(self):
        self.connect()
        self.driver.disconnect()
        replacement = FakeResource()
        self.manager.open_resource.return_value = replacement
        self.connect()
        self.assertIs(self.driver.instr, replacement)
        self.assertEqual(self.manager.open_resource.call_count, 2)

    def test_default_manager_is_obtained_lazily_and_not_closed(self):
        with patch.object(
            pyvisa, "ResourceManager", return_value=self.manager
        ) as factory:
            driver = dp800()
            factory.assert_not_called()
            driver.connect("TCPIP::example::INSTR")
            factory.assert_called_once_with()
            driver.disconnect()
        self.manager.close.assert_not_called()

    def test_open_failure_never_closes_manager(self):
        error = OSError("Open failed")
        self.manager.open_resource.side_effect = error
        for injected in (False, True):
            with (
                self.subTest(injected=injected),
                patch.object(pyvisa, "ResourceManager", return_value=self.manager),
            ):
                with self.assertRaises(OSError) as raised:
                    if injected:
                        self.connect()
                    else:
                        self.driver.connect("TCPIP::example::INSTR")
                self.assertIs(raised.exception, error)
                self.assertIsNone(self.driver.instr)
                self.assertEqual(self.resource.closed, 0)
                self.manager.close.assert_not_called()

    def test_initialization_failures_close_resource_and_allow_retry(self):
        for stage in ("configure", "remote", "identity", "interrupt"):
            with self.subTest(stage=stage):
                self.setUp()
                error = (
                    KeyboardInterrupt() if stage == "interrupt" else ValueError(stage)
                )
                if stage == "configure":
                    self.resource.fail_setting = "timeout"
                elif stage == "remote":
                    self.resource.write_errors[":SYST:REM"] = error
                else:
                    self.resource.query_error = error
                with self.assertRaises(type(error)):
                    self.connect(timeout=500)
                self.assertEqual(self.resource.closed, 1)
                self.assertIsNone(self.driver.instr)
                self.assertIsNone(self.driver._resource_manager)
                self.manager.close.assert_not_called()
                replacement = FakeResource()
                self.manager.open_resource.return_value = replacement
                self.connect()
                self.assertIs(self.driver.instr, replacement)

    def test_failed_initialization_preserves_error_when_resource_close_fails(self):
        error = ValueError("Identity failed")
        self.resource.query_error = error
        self.resource.close_error = OSError("Resource close failed")
        with patch.object(pyvisa, "ResourceManager", return_value=self.manager):
            with self.assertLogs("dp800.dp800", level="WARNING"):
                with self.assertRaises(ValueError) as raised:
                    self.driver.connect("TCPIP::example::INSTR")
        self.assertIs(raised.exception, error)
        self.assertEqual(self.resource.closed, 1)
        self.manager.close.assert_not_called()

    def test_non_message_resource_is_closed(self):
        resource = MagicMock(spec=Resource)
        self.manager.open_resource.return_value = resource
        with self.assertRaises(TypeError):
            self.connect()
        resource.close.assert_called_once_with()
        self.assertIsNone(self.driver.instr)

    def test_unknown_private_and_method_attributes_are_rejected_with_cleanup(self):
        for kwargs in (
            {"unknown_setting": 1},
            {"_encoding": "utf-16"},
            {"write": None},
        ):
            with self.subTest(kwargs=kwargs):
                self.setUp()
                with self.assertRaises(ValueError):
                    self.connect(**kwargs)
                self.assertEqual(self.resource.closed, 1)
                self.assertIsNone(self.driver.instr)

    def test_disconnect_attempts_all_commands_and_closes_after_io_failure(self):
        self.connect()
        error = OSError("Output disable failed")
        self.resource.write_errors[":OUTP  CH1,OFF"] = error
        self.resource.write_errors[":SYST:LOC"] = OSError("Local mode failed")
        self.resource.close_error = OSError("Close failed")
        with self.assertLogs("dp800.dp800", level="WARNING"):
            with self.assertRaises(OSError) as raised:
                self.driver.disconnect()
        self.assertIs(raised.exception, error)
        self.assertIn(":OUTP  CH3,OFF", self.resource.commands)
        self.assertIn(":SYST:LOC", self.resource.commands)
        self.assertEqual(self.resource.closed, 1)
        self.assertIsNone(self.driver.instr)
        self.manager.close.assert_not_called()
        self.driver.disconnect()

    def test_resource_close_failure_clears_state_without_closing_manager(self):
        with patch.object(pyvisa, "ResourceManager", return_value=self.manager):
            self.driver.connect("TCPIP::example::INSTR")
        self.resource.close_error = OSError("Close failed")
        with self.assertRaises(OSError):
            self.driver.disconnect()
        self.manager.close.assert_not_called()
        self.assertIsNone(self.driver.instr)
        self.assertIsNone(self.driver._resource_manager)

    def test_disconnected_io_raises_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            self.driver.get_id()
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            self.driver.set_voltage(1)

    def test_reset_remains_an_explicit_operation(self):
        self.connect()
        self.driver.reset()
        self.assertEqual(self.resource.commands[-1], "*RST")

    def test_existing_response_types_and_coupling_list(self):
        self.connect()
        self.resource.responses.update(
            {
                ":MEAS?": "1.2",
                ":MEAS:ALL?": "1.2,0.1,0.12",
                ":APPL? CH1,VOLT": "1.2",
                ":APPL?": "CH1,30V/3A,1.2,0.1",
                ":OUTP:OCP:ALAR?": "YES",
                ":OUTP:OVP:ALAR?": "NO",
            }
        )
        self.assertEqual(self.driver.measure(), "1.2")
        self.assertEqual(self.driver.measure("ALL"), ["1.2", "0.1", "0.12"])
        self.assertEqual(self.driver.get_apply(1, "VOLT"), 1.2)
        self.assertEqual(self.driver.get_apply(), ("CH1", "30V/3A", 1.2, 0.1))
        self.assertTrue(self.driver.get_ocp())
        self.assertFalse(self.driver.get_ovp())
        self.driver.set_trigger_coupling_channels(["CH1", "CH2"])
        self.assertEqual(self.resource.commands[-1], ":INST:COUP CH1,CH2")


class VirtualConnectionTests(unittest.TestCase):
    def test_virtual_connection_never_opens_or_closes_manager(self):
        manager = MagicMock(spec=pyvisa.ResourceManager)
        driver = VirtualDP800()
        with patch.object(pyvisa, "ResourceManager") as factory:
            driver.connect("virtual", resource_manager=manager)
            self.assertIs(driver._resource_manager, manager)
            with self.assertRaises(RuntimeError):
                driver.connect("virtual")
            driver.disconnect()
            driver.disconnect()
            self.assertIsNone(driver._resource_manager)
            driver.connect("virtual")
            factory.assert_not_called()
        manager.open_resource.assert_not_called()
        manager.close.assert_not_called()

    def test_virtual_connection_rejects_protocol_conflicts(self):
        driver = VirtualDP800()
        for kwargs in (
            {"encoding": "utf-16"},
            {"read_termination": None},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                driver.connect("virtual", **kwargs)
        driver.connect(
            "virtual", encoding="ascii", read_termination="\n", write_termination="\n"
        )


if __name__ == "__main__":
    unittest.main()
