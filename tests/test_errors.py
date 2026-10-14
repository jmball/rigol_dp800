# SPDX-License-Identifier: GPL-3.0-or-later

"""Hardware-free coverage of SCPI error checks and timeout diagnostics."""

import unittest
from unittest.mock import MagicMock, patch

import pyvisa

from dp800 import DP800, InstrumentError
from virtual_dp800 import DP800 as VirtualDP800

from test_driver import FakeResource


class ErrorTests(unittest.TestCase):
    def setUp(self):
        self.driver = DP800()
        self.resource = FakeResource()
        self.manager = MagicMock(spec=pyvisa.ResourceManager)
        self.manager.open_resource.return_value = self.resource

    def connect(self):
        self.driver.connect("TCPIP::example::INSTR", resource_manager=self.manager)

    def timeout_query(self):
        original = pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout)
        query = self.resource.query

        def scripted_query(command):
            if command == ":MEAS?":
                self.resource.io_events.append(command)
                raise original
            return query(command)

        return original, patch.object(
            self.resource, "query", side_effect=scripted_query
        )

    def test_connect_only_reads_and_clears_stale_errors(self):
        self.resource.queued_errors = ['-113,"Old error"', '-222,"Another old error"']
        self.connect()
        self.assertEqual(
            self.resource.io_events,
            [":SYST:ERR?", ":SYST:ERR?", ":SYST:ERR?"],
        )
        self.assertEqual(self.resource.queued_errors, [])
        self.assertIs(self.driver._instr, self.resource)
        self.resource.responses[":MEAS?"] = "1.2"
        self.assertEqual(self.driver.measure(), "1.2")

    def test_connect_closes_resource_if_queue_cannot_be_read(self):
        for failure in (OSError("Queue unavailable"), ValueError("Bad response")):
            with self.subTest(failure=failure):
                self.setUp()
                self.resource.diagnostic_error = failure
                with self.assertRaises(type(failure)) as raised:
                    self.connect()
                self.assertIs(raised.exception, failure)
                self.assertIsNone(self.driver._instr)
                self.assertEqual(self.resource.closed, 1)
                self.assertNotIn(":SYST:REM", self.resource.commands)

    def test_remote_mode_is_explicit_and_checks_instrument_errors(self):
        self.resource.queued_errors = ['-113,"Stale error"']
        self.resource.errors_after_write[":SYST:REM"] = ['-222,"Remote mode rejected"']
        self.connect()
        self.assertNotIn(":SYST:REM", self.resource.commands)
        with self.assertRaises(InstrumentError) as raised:
            self.driver.set_remote()
        self.assertEqual(str(raised.exception), '-222,"Remote mode rejected"')
        self.assertEqual(self.resource.closed, 0)
        self.assertIs(self.driver._instr, self.resource)

    def test_writes_report_only_raw_error_responses(self):
        self.connect()
        errors = [' -222 , "Data out of range"', '-221,"Settings conflict, voltage"']
        self.resource.errors_after_write[":VOLT 5.0"] = errors
        with self.assertRaises(InstrumentError) as raised:
            self.driver.set_voltage(5.0)
        self.assertEqual(str(raised.exception), "\n".join(errors))
        self.assertFalse(hasattr(raised.exception, "command"))
        self.assertEqual(self.resource.queued_errors, [])
        self.assertEqual(self.driver._write("*CLS"), len("*CLS"))

    def test_successful_queries_read_response_before_error_checking(self):
        self.connect()
        self.resource.responses[":MEAS?"] = "1.2"
        self.resource.errors_after_query[":MEAS?"] = ['-222,"Invalid channel"']
        with self.assertRaises(InstrumentError) as raised:
            self.driver.measure()
        self.assertEqual(str(raised.exception), '-222,"Invalid channel"')
        self.assertEqual(
            self.resource.io_events[-3:], [":MEAS?", ":SYST:ERR?", ":SYST:ERR?"]
        )

    def test_query_timeout_reports_errors_using_configured_visa_settings(self):
        self.connect()
        self.resource.timeout = 1234
        self.resource.query_delay = 0.1
        self.resource.queued_errors = ['-222,"Invalid channel"']
        original, query_patch = self.timeout_query()
        with query_patch:
            with self.assertRaises(InstrumentError) as raised:
                self.driver.measure()
        self.assertIs(raised.exception.__cause__, original)
        self.assertEqual(str(raised.exception), '-222,"Invalid channel"')
        self.assertEqual(self.resource.timeout, 1234)
        self.assertEqual(self.resource.query_delay, 0.1)
        self.assertEqual(self.resource.error_query_delays[-2:], [None, None])
        self.assertEqual(self.resource.error_queries[-2:], [1234, 1234])

    def test_query_timeout_preserved_for_empty_malformed_or_failed_diagnostics(self):
        for result in (
            '0,"No error"',
            "1.234",
            "0,unquoted",
            OSError("Disconnected"),
            pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout),
        ):
            with self.subTest(result=result):
                self.setUp()
                self.connect()
                self.resource.timeout = 1234
                if isinstance(result, Exception):
                    self.resource.diagnostic_error = result
                else:
                    self.resource.queued_errors = [result]
                original, query_patch = self.timeout_query()
                cause = OSError("Original low-level cause")
                original.__cause__ = cause
                with query_patch:
                    with self.assertRaises(pyvisa.errors.VisaIOError) as raised:
                        self.driver.measure()
                self.assertIs(raised.exception, original)
                self.assertIs(raised.exception.__cause__, cause)
                self.assertEqual(self.resource.timeout, 1234)

    def test_non_timeout_query_errors_do_not_run_diagnostics(self):
        self.connect()
        before = list(self.resource.error_queries)
        error = pyvisa.errors.VisaIOError(
            pyvisa.constants.StatusCode.error_connection_lost
        )
        self.resource.query_error = error
        with self.assertRaises(pyvisa.errors.VisaIOError) as raised:
            self.driver.measure()
        self.assertIs(raised.exception, error)
        self.assertEqual(self.resource.error_queries, before)

    def test_failed_transport_write_is_not_followed_by_diagnostics(self):
        self.connect()
        before = list(self.resource.error_queries)
        error = OSError("Write failed")
        self.resource.write_errors["*CLS"] = error
        with self.assertRaises(OSError) as raised:
            self.driver.clear_event_registers()
        self.assertIs(raised.exception, error)
        self.assertEqual(self.resource.error_queries, before)

    def test_get_errors_returns_raw_responses_and_consumes_the_queue(self):
        self.connect()
        errors = ['-222,"Bad value, ""voltage"""', '-221,"Conflict"']
        self.resource.queued_errors = list(errors)
        self.assertEqual(self.driver.get_errors(), errors)
        self.assertEqual(self.driver.get_errors(), [])
        self.resource.queued_errors = [' +0, "No error" \n']
        self.assertEqual(self.driver.get_errors(), [])
        self.assertEqual(VirtualDP800().get_errors(), [])
        self.driver.disconnect()
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            self.driver.get_errors()

    def test_normal_error_query_failure_is_visible(self):
        self.connect()
        self.resource.queued_errors = ["malformed"]
        with self.assertRaises(ValueError):
            self.driver.clear_event_registers()

    def test_disconnect_closes_and_attempts_all_commands_despite_instrument_errors(
        self,
    ):
        self.connect()
        self.resource.errors_after_write[":OUTP  CH2,OFF"] = [
            '-222,"Invalid channel 2"'
        ]
        self.resource.errors_after_write[":OUTP  CH3,OFF"] = [
            '-222,"Invalid channel 3"'
        ]
        with self.assertLogs("dp800.dp800", level="WARNING"):
            with self.assertRaises(InstrumentError) as raised:
                self.driver.disconnect()
        self.assertEqual(str(raised.exception), '-222,"Invalid channel 2"')
        self.assertIn(":OUTP  CH3,OFF", self.resource.commands)
        self.assertIn(":SYST:LOC", self.resource.commands)
        self.assertEqual(self.resource.closed, 1)
        self.assertIsNone(self.driver._instr)


if __name__ == "__main__":
    unittest.main()
