# SPDX-License-Identifier: GPL-3.0-or-later

from unittest.mock import patch
import pytest
import pyvisa
from dp800 import InstrumentError
from virtual_dp800 import DP800 as VirtualDP800
from tests.fakes import make_fake_visa


class TestError:

    @pytest.fixture(autouse=True)
    def setup(self, fake_visa, caplog):
        self.driver, self.resource, self.manager = fake_visa
        self.caplog = caplog

    def reset(self):
        self.driver, self.resource, self.manager = make_fake_visa()

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

        return (
            original,
            patch.object(self.resource, "query", side_effect=scripted_query),
        )

    def test_writes_report_only_raw_error_responses(self):
        self.connect()
        errors = [' -222 , "Data out of range"', '-221,"Settings conflict, voltage"']
        self.resource.errors_after_write[":VOLT 5.0"] = errors
        with pytest.raises(InstrumentError) as raised:
            self.driver.set_voltage(5.0)
        assert str(raised.value) == "\n".join(errors)
        assert not hasattr(raised.value, "command")
        assert self.resource.queued_errors == []
        assert self.driver._write("*CLS") == len("*CLS")

    def test_successful_queries_read_response_before_error_checking(self):
        self.connect()
        self.resource.responses[":MEAS?"] = "1.2"
        self.resource.errors_after_query[":MEAS?"] = ['-222,"Invalid channel"']
        with pytest.raises(InstrumentError) as raised:
            self.driver.measure()
        assert str(raised.value) == '-222,"Invalid channel"'
        assert self.resource.io_events[-3:] == [":MEAS?", ":SYST:ERR?", ":SYST:ERR?"]

    def test_query_timeout_reports_errors_using_configured_visa_settings(self):
        self.connect()
        self.resource.timeout = 1234
        self.resource.query_delay = 0.1
        self.resource.queued_errors = ['-222,"Invalid channel"']
        original, query_patch = self.timeout_query()
        with query_patch:
            with pytest.raises(InstrumentError) as raised:
                self.driver.measure()
        assert raised.value.__cause__ is original
        assert str(raised.value) == '-222,"Invalid channel"'
        assert self.resource.timeout == 1234
        assert self.resource.query_delay == 0.1
        assert self.resource.error_query_delays[-2:] == [None, None]
        assert self.resource.error_queries[-2:] == [1234, 1234]

    def test_query_timeout_preserved_for_empty_malformed_or_failed_diagnostics(self):
        for result in (
            '0,"No error"',
            "1.234",
            "0,unquoted",
            OSError("Disconnected"),
            pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout),
        ):
            self.reset()
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
                with pytest.raises(pyvisa.errors.VisaIOError) as raised:
                    self.driver.measure()
            assert raised.value is original
            assert raised.value.__cause__ is cause
            assert self.resource.timeout == 1234

    def test_non_timeout_query_errors_do_not_run_diagnostics(self):
        self.connect()
        before = list(self.resource.error_queries)
        error = pyvisa.errors.VisaIOError(
            pyvisa.constants.StatusCode.error_connection_lost
        )
        self.resource.query_error = error
        with pytest.raises(pyvisa.errors.VisaIOError) as raised:
            self.driver.measure()
        assert raised.value is error
        assert self.resource.error_queries == before

    def test_failed_transport_write_is_not_followed_by_diagnostics(self):
        self.connect()
        before = list(self.resource.error_queries)
        error = OSError("Write failed")
        self.resource.write_errors["*CLS"] = error
        with pytest.raises(OSError) as raised:
            self.driver.clear_event_registers()
        assert raised.value is error
        assert self.resource.error_queries == before

    def test_get_errors_returns_raw_responses_and_consumes_the_queue(self):
        self.connect()
        errors = ['-222,"Bad value, ""voltage"""', '-221,"Conflict"']
        self.resource.queued_errors = list(errors)
        assert self.driver.get_errors() == errors
        assert self.driver.get_errors() == []
        self.resource.queued_errors = [' +0, "No error" \n']
        assert self.driver.get_errors() == []
        assert VirtualDP800().get_errors() == []
        self.driver.disconnect()
        with pytest.raises(RuntimeError, match="not connected"):
            self.driver.get_errors()

    def test_get_errors_preserves_batched_error_responses(self):
        self.connect()
        for batch in (
            '-222,"Invalid channel";-221,"Settings conflict"',
            '-222,"Invalid channel",-221,"Settings conflict"',
        ):
            self.resource.queued_errors = [batch]
            assert self.driver.get_errors() == [batch]
            assert self.driver.get_errors() == []

    def test_error_query_timeout_does_not_recursively_check_errors(self):
        self.connect()
        error = pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout)
        self.resource.diagnostic_error = error
        before = len(self.resource.error_queries)
        with pytest.raises(pyvisa.errors.VisaIOError) as raised:
            self.driver.get_errors()
        assert raised.value is error
        assert len(self.resource.error_queries) == before + 1

    def test_query_flag_disables_checks_without_consuming_queued_errors(self):
        self.connect()
        self.resource.responses["*ESR?"] = "20"
        errors = ['-222,"Invalid channel"']
        self.resource.queued_errors = list(errors)
        before = len(self.resource.error_queries)
        assert self.driver._query("*ESR?", check_errors=False) == "20"
        assert len(self.resource.error_queries) == before
        assert self.driver.get_errors() == errors
        self.driver.disconnect()
        with pytest.raises(RuntimeError, match="not connected"):
            self.driver._query("*ESR?", check_errors=False)

    def test_normal_error_query_failure_is_visible(self):
        self.connect()
        self.resource.queued_errors = ["malformed"]
        with pytest.raises(ValueError):
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
        self.caplog.clear()
        with self.caplog.at_level("WARNING", logger="dp800.dp800"):
            with pytest.raises(InstrumentError) as raised:
                self.driver.disconnect()
        assert self.caplog.records
        assert str(raised.value) == '-222,"Invalid channel 2"'
        assert ":OUTP  CH3,OFF" in self.resource.commands
        assert ":SYST:LOC" in self.resource.commands
        assert self.resource.closed == 1
        assert self.driver._instr is None
