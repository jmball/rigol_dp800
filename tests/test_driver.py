# SPDX-License-Identifier: GPL-3.0-or-later

"""Hardware-free regression tests for connection ownership and driver responses."""

import subprocess
import sys
import unittest
import warnings
from unittest.mock import MagicMock, patch

import pyvisa
from pyvisa.resources import MessageBasedResource, Resource

from dp800 import DP800
from virtual_dp800 import DP800 as VirtualDP800


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
        self.closed = 0
        self.on_io = lambda: None

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
        self.driver = DP800()
        self.resource = FakeResource()
        self.manager = MagicMock(spec=pyvisa.ResourceManager)
        self.manager.open_resource.return_value = self.resource
        self.manager.open_resource.side_effect = self.open_resource

    def open_resource(self, resource_name, **kwargs):
        resource = self.manager.open_resource.return_value
        for key, value in kwargs.items():
            if key not in ("access_mode", "open_timeout", "resource_pyclass"):
                setattr(resource, key, value)
        return resource

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

    def test_context_manager_returns_self_and_disconnects(self):
        with self.driver as driver:
            self.assertIs(driver, self.driver)
            self.assertIsNone(driver._instr)
            self.manager.open_resource.assert_not_called()
            self.connect()
        self.assertIsNone(self.driver._instr)
        self.assertEqual(self.resource.closed, 1)
        self.assertEqual(
            self.resource.commands,
            [
                ":SYST:REM",
                ":OUTP  CH1,OFF",
                ":OUTP  CH2,OFF",
                ":OUTP  CH3,OFF",
                ":SYST:LOC",
            ],
        )
        self.manager.close.assert_not_called()

    def test_context_manager_disconnects_on_exception_without_suppressing_it(self):
        self.connect()
        error = ValueError("Block failed")
        with self.assertRaises(ValueError) as raised:
            with self.driver:
                raise error
        self.assertIs(raised.exception, error)
        self.assertIsNone(self.driver._instr)
        self.assertEqual(self.resource.closed, 1)

    def test_disconnected_context_manager_does_not_create_manager(self):
        for driver in (self.driver, VirtualDP800()):
            with self.subTest(driver=type(driver)):
                with patch.object(pyvisa, "ResourceManager") as factory:
                    with driver as entered:
                        self.assertIs(entered, driver)
                    factory.assert_not_called()

    def test_import_preserves_application_warning_and_logging_configuration(self):
        for package in ("dp800", "virtual_dp800"):
            for capture_warnings in (False, True):
                with self.subTest(package=package, capture_warnings=capture_warnings):
                    subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            "import logging, warnings, pyvisa; "
                            "warnings.showwarning = lambda *args, **kwargs: None; "
                            f"logging.captureWarnings({capture_warnings!r}); "
                            "warning_handler = warnings.showwarning; "
                            "root = logging.getLogger(); "
                            "configuration = (root.level, list(root.handlers), list(root.filters)); "
                            f"import {package}; "
                            "assert warnings.showwarning is warning_handler; "
                            "assert (root.level, root.handlers, root.filters) == configuration",
                        ],
                        check=True,
                    )

    def test_configuration_precedes_io_and_publication_without_reset(self):
        def check_initialization():
            self.assertIsNone(self.driver._instr)
            self.assertEqual(self.resource.encoding, "ascii")
            self.assertEqual(self.resource.read_termination, "\n")
            self.assertEqual(self.resource.write_termination, "\n")
            self.assertEqual(self.resource.timeout, 500)

        self.resource.on_io = check_initialization
        self.connect(timeout=500, query_delay=0.1, open_timeout=250)
        self.manager.open_resource.assert_called_once_with(
            "TCPIP::example::INSTR",
            timeout=500,
            query_delay=0.1,
            open_timeout=250,
            encoding="ascii",
            read_termination="\n",
            write_termination="\n",
        )
        self.assertEqual(self.resource.commands, [":SYST:REM"])
        self.assertEqual(self.resource.query_delay, 0.1)
        self.assertIs(self.driver._instr, self.resource)

    def test_matching_protocol_values_are_accepted(self):
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always")
            self.connect(
                encoding="ascii", read_termination="\n", write_termination="\n"
            )
        self.assertEqual(emitted, [])
        self.assertIs(self.driver._instr, self.resource)

    def test_protocol_conflicts_warn_and_connect_with_driver_values(self):
        for kwargs in (
            {"encoding": "utf-16"},
            {"read_termination": None},
            {"write_termination": "\r\n"},
        ):
            with self.subTest(kwargs=kwargs):
                self.setUp()
                with self.assertWarns(UserWarning) as emitted:
                    self.connect(**kwargs)
                self.assertIn(f"driver owns {next(iter(kwargs))}", str(emitted.warning))
                self.assertIn("will be ignored", str(emitted.warning))
                self.manager.open_resource.assert_called_once_with(
                    "TCPIP::example::INSTR",
                    encoding="ascii",
                    read_termination="\n",
                    write_termination="\n",
                )
                self.assertIs(self.driver._instr, self.resource)
                self.assertEqual(self.resource.encoding, "ascii")
                self.assertEqual(self.resource.read_termination, "\n")
                self.assertEqual(self.resource.write_termination, "\n")
                self.assertEqual(self.resource.commands, [":SYST:REM"])

    def test_connecting_twice_raises_without_touching_existing_connection(self):
        self.connect()
        with self.assertRaises(RuntimeError):
            self.connect()
        self.manager.open_resource.assert_called_once()
        self.assertEqual(self.resource.closed, 0)
        self.assertIs(self.driver._instr, self.resource)

    def test_disconnect_is_idempotent_and_caller_manager_remains_open(self):
        self.driver.disconnect()
        self.connect()
        self.driver.disconnect()
        self.driver.disconnect()
        self.assertEqual(
            self.resource.commands[1:],
            [
                ":OUTP  CH1,OFF",
                ":OUTP  CH2,OFF",
                ":OUTP  CH3,OFF",
                ":SYST:LOC",
            ],
        )
        self.assertEqual(self.resource.closed, 1)
        self.assertIsNone(self.driver._instr)
        self.manager.close.assert_not_called()

    def test_reconnect_after_disconnect(self):
        self.connect()
        self.driver.disconnect()
        replacement = FakeResource()
        self.manager.open_resource.return_value = replacement
        self.connect()
        self.assertIs(self.driver._instr, replacement)
        self.assertEqual(self.manager.open_resource.call_count, 2)

    def test_default_manager_is_obtained_lazily_and_not_closed(self):
        with patch.object(
            pyvisa, "ResourceManager", return_value=self.manager
        ) as factory:
            driver = DP800()
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
                self.assertIsNone(self.driver._instr)
                self.assertEqual(self.resource.closed, 0)
                self.manager.close.assert_not_called()

    def test_initialization_failures_close_resource_and_allow_retry(self):
        for stage in ("remote", "interrupt"):
            with self.subTest(stage=stage):
                self.setUp()
                error = (
                    KeyboardInterrupt() if stage == "interrupt" else ValueError(stage)
                )
                self.resource.write_errors[":SYST:REM"] = error
                with self.assertRaises(type(error)):
                    self.connect(timeout=500)
                self.assertEqual(self.resource.closed, 1)
                self.assertIsNone(self.driver._instr)
                self.manager.close.assert_not_called()
                replacement = FakeResource()
                self.manager.open_resource.return_value = replacement
                self.connect()
                self.assertIs(self.driver._instr, replacement)

    def test_failed_initialization_preserves_error_when_resource_close_fails(self):
        error = ValueError("Remote mode failed")
        self.resource.write_errors[":SYST:REM"] = error
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
        self.assertIsNone(self.driver._instr)

    def test_resource_kwargs_are_forwarded_without_driver_validation(self):
        self.manager.open_resource.side_effect = None
        kwargs = {
            "access_mode": pyvisa.constants.AccessModes.exclusive_lock,
            "open_timeout": 250,
            "resource_pyclass": FakeResource,
            "unknown_setting": 1,
            "_encoding": "utf-16",
            "write": None,
        }
        self.connect(**kwargs)
        self.manager.open_resource.assert_called_once_with(
            "TCPIP::example::INSTR",
            **kwargs,
            encoding="ascii",
            read_termination="\n",
            write_termination="\n",
        )
        self.assertIs(self.driver._instr, self.resource)

    def test_disconnect_attempts_all_commands_and_closes_after_io_failure(self):
        self.connect()
        error = OSError("Output disable failed")
        self.resource.write_errors[":OUTP  CH1,OFF"] = error
        self.resource.write_errors[":SYST:LOC"] = OSError("Local mode failed")
        self.resource.close_error = OSError("Close failed")
        with self.assertLogs("dp800.dp800", level="WARNING") as captured:
            with self.assertRaises(OSError) as raised:
                self.driver.disconnect()
        command_log = next(
            record
            for record in captured.records
            if "Additional disconnect error" in record.getMessage()
        )
        self.assertIn(":SYST:LOC", command_log.getMessage())
        self.assertIs(command_log.exc_info[1], self.resource.write_errors[":SYST:LOC"])
        self.assertIs(raised.exception, error)
        self.assertIn(":OUTP  CH3,OFF", self.resource.commands)
        self.assertIn(":SYST:LOC", self.resource.commands)
        self.assertEqual(self.resource.closed, 1)
        self.assertIsNone(self.driver._instr)
        self.manager.close.assert_not_called()
        self.driver.disconnect()

    def test_resource_close_failure_clears_state_without_closing_manager(self):
        with patch.object(pyvisa, "ResourceManager", return_value=self.manager):
            self.driver.connect("TCPIP::example::INSTR")
        self.resource.close_error = OSError("Close failed")
        with self.assertRaises(OSError):
            self.driver.disconnect()
        self.manager.close.assert_not_called()
        self.assertIsNone(self.driver._instr)

    def test_disconnected_io_raises_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            self.driver.identity
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            self.driver.set_voltage(1)

    def test_io_wrappers_preserve_visa_return_values_and_exceptions(self):
        self.connect()
        self.assertEqual(self.driver._write("*CLS"), len("*CLS"))
        self.resource.responses[":MEAS?"] = "  1.200\n"
        self.assertEqual(self.driver._query(":MEAS?"), "  1.200\n")
        error = pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout)
        self.resource.write_errors["*CLS"] = error
        self.resource.query_error = error
        for operation, command in (
            (self.driver._write, "*CLS"),
            (self.driver._query, ":MEAS?"),
        ):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(pyvisa.errors.VisaIOError) as raised:
                    operation(command)
                self.assertIs(raised.exception, error)

    def test_reset_remains_an_explicit_operation(self):
        self.connect()
        self.driver.reset()
        self.assertEqual(self.resource.commands[-1], "*RST")

    def test_common_command_properties_read_fresh_values(self):
        self.connect()
        for name, command, response, expected in (
            (
                "identity",
                "*IDN?",
                "RIGOL,DP832,serial,version",
                ["RIGOL", "DP832", "serial", "version"],
            ),
            ("standard_event_enable_register", "*ESE?", "10", 10),
            ("status_byte_enable_register", "*SRE?", "32", 32),
            ("status_byte_register", "*STB?", "16", 16),
            ("power_on_status_clear_bit", "*PSC?", "1", 1),
            ("option_installation_status", "*OPT?", "DP8-LAN,0", "DP8-LAN,0"),
        ):
            with self.subTest(property=name):
                self.resource.responses[command] = response
                self.assertEqual(getattr(self.driver, name), expected)
                self.assertEqual(getattr(self.driver, name), expected)
                self.assertEqual(self.resource.commands[-2:], [command, command])
                self.driver.disconnect()
                with self.assertRaisesRegex(RuntimeError, "not connected"):
                    getattr(self.driver, name)
                self.connect()

    def test_common_command_property_setters_and_validation(self):
        self.connect()
        for name, command, values in (
            ("standard_event_enable_register", "*ESE", (0, 10, 255)),
            ("status_byte_enable_register", "*SRE", (0, 32, 255)),
            ("power_on_status_clear_bit", "*PSC", (0, 1)),
        ):
            with self.subTest(property=name):
                for value in values:
                    setattr(self.driver, name, value)
                    self.assertEqual(self.resource.commands[-1], f"{command} {value}")
                if command != "*PSC":
                    before = list(self.resource.commands)
                    for value in (-1, 256):
                        with self.assertRaises(ValueError):
                            setattr(self.driver, name, value)
                    self.assertEqual(self.resource.commands, before)
                self.driver.disconnect()
                with self.assertRaisesRegex(RuntimeError, "not connected"):
                    setattr(self.driver, name, 1)
                self.connect()

    def test_common_command_read_only_properties_and_virtual_placeholders(self):
        virtual = VirtualDP800()
        for driver in (self.driver, virtual):
            for name in (
                "identity",
                "status_byte_register",
                "option_installation_status",
            ):
                with self.subTest(driver=type(driver), property=name):
                    with self.assertRaises(AttributeError):
                        setattr(driver, name, None)
        self.assertEqual(virtual.identity, "Virtual Rigol DP800")
        self.assertEqual(virtual.option_installation_status, [""])
        self.assertEqual(virtual.status_byte_register, 0)
        for name in (
            "standard_event_enable_register",
            "status_byte_enable_register",
            "power_on_status_clear_bit",
        ):
            setattr(virtual, name, 1)
            self.assertEqual(getattr(virtual, name), 0)

    def test_event_register_and_opc_remain_explicit_methods(self):
        self.connect()
        self.resource.responses.update({"*ESR?": "20", "*OPC?": "1"})
        self.assertEqual(self.driver.get_standard_event_register(), 20)
        self.driver.set_opc()
        self.assertEqual(self.driver.get_opc(), 1)
        self.assertEqual(self.resource.commands[-3:], ["*ESR?", "*OPC", "*OPC?"])

    def test_identity_and_connection_logging_are_caller_responsibilities(self):
        with patch("dp800.dp800.logger.info") as log_info:
            self.connect()
        log_info.assert_not_called()
        self.assertEqual(self.resource.commands, [":SYST:REM"])
        self.assertEqual(self.driver.identity, ["RIGOL", "DP832", "serial", "version"])
        self.assertEqual(self.resource.commands, [":SYST:REM", "*IDN?"])
        with patch("virtual_dp800.virtual_dp800.logger.info") as virtual_log_info:
            VirtualDP800().connect("virtual")
        virtual_log_info.assert_not_called()

    def test_additional_properties_query_and_parse_fresh_values(self):
        self.connect()
        for name, command, response, expected in (
            ("delay_end_state", ":DELAY:ENDS?", "LAST", "LAST"),
            ("delay_groups", ":DELAY:GROUP?", "12", 12),
            ("keylock_enabled", ":SYST:KLOC:STAT?", "ON", True),
            ("keylock_enabled", ":SYST:KLOC:STAT?", "OFF", False),
            ("trigger_coupling_channels", ":INST:COUP?", "ALL", "ALL"),
            ("trigger_coupling_channels", ":INST:COUP?", "NONE", "NONE"),
            (
                "trigger_coupling_channels",
                ":INST:COUP?",
                "CH1:30V/3A,CH2:30V/3A",
                ["CH1:30V/3A", "CH2:30V/3A"],
            ),
            ("selected_channel", ":INST:NSEL?", "2", 2),
            ("self_test_results", "*TST?", "PASS,PASS,FAIL", ["PASS", "PASS", "FAIL"]),
            ("temperature_test_result", ":SYST:SELF:TEST:TEMP?", "23.67", 23.67),
        ):
            with self.subTest(property=name, response=response):
                self.resource.responses[command] = response
                self.assertEqual(getattr(self.driver, name), expected)
                self.assertEqual(getattr(self.driver, name), expected)
                self.assertEqual(self.resource.commands[-2:], [command, command])
                error = OSError("Query failed")
                self.resource.query_error = error
                with self.assertRaises(OSError) as raised:
                    getattr(self.driver, name)
                self.assertIs(raised.exception, error)
                self.resource.query_error = None
                self.driver.disconnect()
                with self.assertRaisesRegex(RuntimeError, "not connected"):
                    getattr(self.driver, name)
                self.connect()

    def test_additional_property_assignments_preserve_commands(self):
        self.connect()
        for name, value, command in (
            ("delay_end_state", "ON", ":DELAY:ENDS ON"),
            ("delay_end_state", "OFF", ":DELAY:ENDS OFF"),
            ("delay_end_state", "LAST", ":DELAY:ENDS LAST"),
            ("delay_groups", 12, ":DELAY:GROUP 12"),
            ("keylock_enabled", True, ":SYST:KLOC:STAT ON"),
            ("keylock_enabled", False, ":SYST:KLOC:STAT OFF"),
            ("trigger_coupling_channels", ["CH1", "CH2"], ":INST:COUP CH1,CH2"),
            ("trigger_coupling_channels", "ALL", ":INST:COUP ALL"),
            ("trigger_coupling_channels", "NONE", ":INST:COUP NONE"),
            ("selected_channel", 2, ":INST CH2"),
        ):
            with self.subTest(property=name, value=value):
                setattr(self.driver, name, value)
                self.assertEqual(self.resource.commands[-1], command)
                error = OSError("Write failed")
                self.resource.write_errors[command] = error
                with self.assertRaises(OSError) as raised:
                    setattr(self.driver, name, value)
                self.assertIs(raised.exception, error)
                self.resource.write_errors.clear()
                self.driver.disconnect()
                with self.assertRaisesRegex(RuntimeError, "not connected"):
                    setattr(self.driver, name, value)
                self.connect()

    def test_selected_channel_and_implicit_channel_commands(self):
        self.connect()
        self.driver.selected_channel = 2
        self.driver.set_voltage(5.0)
        self.driver.set_voltage(3.0, channel=1)
        self.assertEqual(
            self.resource.commands[-3:], [":INST CH2", ":VOLT 5.0", ":SOUR1:VOLT 3.0"]
        )

    def test_additional_virtual_properties_and_read_only_test_results(self):
        virtual = VirtualDP800()
        for name, value, expected in (
            ("delay_end_state", "LAST", ""),
            ("delay_groups", 12, 0),
            ("keylock_enabled", True, False),
            ("trigger_coupling_channels", ["CH1", "CH2"], ""),
            ("selected_channel", 2, 0),
        ):
            with self.subTest(property=name):
                setattr(virtual, name, value)
                self.assertEqual(getattr(virtual, name), expected)
        self.assertEqual(virtual.self_test_results, [])
        self.assertEqual(virtual.temperature_test_result, 0.0)
        for driver in (self.driver, virtual):
            for name in ("self_test_results", "temperature_test_result"):
                with self.subTest(driver=type(driver), property=name):
                    with self.assertRaises(AttributeError):
                        setattr(driver, name, None)

    def test_output_enable_queries_state_for_implicit_and_explicit_channels(self):
        self.connect()
        for channel in (None, 1, 2, 3):
            command = ":OUTP?" if channel is None else f":OUTP? CH{channel}"
            for response, expected in (("ON", True), ("OFF", False)):
                with self.subTest(channel=channel, response=response):
                    self.resource.responses[command] = response
                    self.assertIs(self.driver.get_output_enable(channel), expected)
                    self.assertEqual(self.resource.commands[-1], command)

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
        self.driver.trigger_coupling_channels = ["CH1", "CH2"]
        self.assertEqual(self.resource.commands[-1], ":INST:COUP CH1,CH2")


class VirtualConnectionTests(unittest.TestCase):
    def test_virtual_context_manager_disconnects_on_normal_and_exceptional_exit(self):
        for error in (None, ValueError("Block failed")):
            with self.subTest(error=error):
                driver = VirtualDP800()

                def use_driver():
                    with driver as entered:
                        self.assertIs(entered, driver)
                        driver.connect("virtual")
                        self.assertTrue(driver._connected)
                        if error is not None:
                            raise error

                if error is None:
                    use_driver()
                else:
                    with self.assertRaises(ValueError) as raised:
                        use_driver()
                    self.assertIs(raised.exception, error)
                self.assertFalse(driver._connected)

    def test_virtual_connection_never_opens_or_closes_manager(self):
        manager = MagicMock(spec=pyvisa.ResourceManager)
        driver = VirtualDP800()
        with patch.object(pyvisa, "ResourceManager") as factory:
            driver.connect("virtual", resource_manager=manager)
            with self.assertRaises(RuntimeError):
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
            with self.subTest(kwargs=kwargs):
                driver = VirtualDP800()
                with self.assertWarns(UserWarning) as emitted:
                    driver.connect("virtual", **kwargs)
                self.assertIn(f"driver owns {next(iter(kwargs))}", str(emitted.warning))
                self.assertIn("will be ignored", str(emitted.warning))
                self.assertTrue(driver._connected)
                driver.disconnect()
                with warnings.catch_warnings(record=True) as emitted_matching:
                    warnings.simplefilter("always")
                    driver.connect(
                        "virtual",
                        encoding="ascii",
                        read_termination="\n",
                        write_termination="\n",
                    )
                self.assertEqual(emitted_matching, [])


if __name__ == "__main__":
    unittest.main()
