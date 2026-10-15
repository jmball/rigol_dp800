# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess
import sys
import warnings
from unittest.mock import MagicMock, patch
import pytest
import pyvisa
from pyvisa.resources import Resource
from dp800 import DP800
from virtual_dp800 import DP800 as VirtualDP800
from tests.fakes import FakeResource, make_fake_visa


class TestConnection:

    @pytest.fixture(autouse=True)
    def setup(self, fake_visa, caplog):
        self.driver, self.resource, self.manager = fake_visa
        self.caplog = caplog

    def reset(self):
        self.driver, self.resource, self.manager = make_fake_visa()

    def connect(self, **kwargs):
        self.driver.connect(
            "TCPIP::example::INSTR", resource_manager=self.manager, **kwargs
        )

    def test_import_does_not_create_resource_manager(self):
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from unittest.mock import patch; import pyvisa; p = patch.object(pyvisa, 'ResourceManager'); m = p.start(); import dp800; import virtual_dp800; m.assert_not_called()",
            ],
            check=True,
        )

    def test_context_manager_returns_self_and_disconnects(self):
        with self.driver as driver:
            assert driver is self.driver
            assert driver._instr is None
            self.manager.open_resource.assert_not_called()
            self.connect()
        assert self.driver._instr is None
        assert self.resource.closed == 1
        assert self.resource.commands == [
            ":OUTP  CH1,OFF",
            ":OUTP  CH2,OFF",
            ":OUTP  CH3,OFF",
            ":SYST:LOC",
        ]
        self.manager.close.assert_not_called()

    def test_context_manager_disconnects_on_exception_without_suppressing_it(self):
        self.connect()
        error = ValueError("Block failed")
        with pytest.raises(ValueError) as raised:
            with self.driver:
                raise error
        assert raised.value is error
        assert self.driver._instr is None
        assert self.resource.closed == 1

    def test_disconnected_context_manager_does_not_create_manager(self):
        for driver in (self.driver, VirtualDP800()):
            with patch.object(pyvisa, "ResourceManager") as factory:
                with driver as entered:
                    assert entered is driver
                factory.assert_not_called()

    def test_import_preserves_application_warning_and_logging_configuration(self):
        for package in ("dp800", "virtual_dp800"):
            for capture_warnings in (False, True):
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        f"import logging, warnings, pyvisa; warnings.showwarning = lambda *args, **kwargs: None; logging.captureWarnings({capture_warnings!r}); warning_handler = warnings.showwarning; root = logging.getLogger(); configuration = (root.level, list(root.handlers), list(root.filters)); import {package}; assert warnings.showwarning is warning_handler; assert (root.level, root.handlers, root.filters) == configuration",
                    ],
                    check=True,
                )

    def test_configuration_and_resource_assignment_precede_queue_read_without_reset(
        self,
    ):

        def check_initialization():
            assert self.driver._instr is self.resource
            assert self.resource.encoding == "ascii"
            assert self.resource.read_termination == "\n"
            assert self.resource.write_termination == "\n"
            assert self.resource.timeout == 500

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
        assert self.resource.commands == []
        assert self.resource.query_delay == 0.1
        assert self.driver._instr is self.resource

    def test_matching_protocol_values_are_accepted(self):
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always")
            self.connect(
                encoding="ascii", read_termination="\n", write_termination="\n"
            )
        assert emitted == []
        assert self.driver._instr is self.resource

    def test_protocol_conflicts_warn_and_connect_with_driver_values(self):
        for kwargs in (
            {"encoding": "utf-16"},
            {"read_termination": None},
            {"write_termination": "\r\n"},
        ):
            self.reset()
            with pytest.warns(UserWarning) as emitted:
                self.connect(**kwargs)
            assert f"driver owns {next(iter(kwargs))}" in str(emitted[0].message)
            assert "will be ignored" in str(emitted[0].message)
            self.manager.open_resource.assert_called_once_with(
                "TCPIP::example::INSTR",
                encoding="ascii",
                read_termination="\n",
                write_termination="\n",
            )
            assert self.driver._instr is self.resource
            assert self.resource.encoding == "ascii"
            assert self.resource.read_termination == "\n"
            assert self.resource.write_termination == "\n"
            assert self.resource.commands == []

    def test_connecting_twice_raises_without_touching_existing_connection(self):
        self.connect()
        with pytest.raises(RuntimeError):
            self.connect()
        self.manager.open_resource.assert_called_once()
        assert self.resource.closed == 0
        assert self.driver._instr is self.resource

    def test_disconnect_is_idempotent_and_caller_manager_remains_open(self):
        self.driver.disconnect()
        self.connect()
        self.driver.disconnect()
        self.driver.disconnect()
        assert self.resource.commands == [
            ":OUTP  CH1,OFF",
            ":OUTP  CH2,OFF",
            ":OUTP  CH3,OFF",
            ":SYST:LOC",
        ]
        assert self.resource.closed == 1
        assert self.driver._instr is None
        self.manager.close.assert_not_called()

    def test_reconnect_after_disconnect(self):
        self.connect()
        self.driver.disconnect()
        replacement = FakeResource()
        self.manager.open_resource.return_value = replacement
        self.connect()
        assert self.driver._instr is replacement
        assert self.manager.open_resource.call_count == 2

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
            with patch.object(pyvisa, "ResourceManager", return_value=self.manager):
                with pytest.raises(OSError) as raised:
                    if injected:
                        self.connect()
                    else:
                        self.driver.connect("TCPIP::example::INSTR")
                assert raised.value is error
                assert self.driver._instr is None
                assert self.resource.closed == 0
                self.manager.close.assert_not_called()

    @pytest.mark.parametrize(
        "error",
        [ValueError("Queue failed"), OSError("Queue failed"), KeyboardInterrupt()],
        ids=["invalid-response", "transport-error", "interrupt"],
    )
    def test_initialization_failures_close_resource_and_allow_retry(self, error):
        self.resource.diagnostic_error = error
        with pytest.raises(type(error)) as raised:
            self.connect(timeout=500)
        assert raised.value is error
        assert self.resource.closed == 1
        assert self.driver._instr is None
        self.manager.close.assert_not_called()
        replacement = FakeResource()
        self.manager.open_resource.return_value = replacement
        self.connect()
        assert self.driver._instr is replacement

    def test_failed_initialization_preserves_error_when_resource_close_fails(self):
        error = ValueError("Error queue failed")
        self.resource.diagnostic_error = error
        self.resource.close_error = OSError("Resource close failed")
        with patch.object(pyvisa, "ResourceManager", return_value=self.manager):
            self.caplog.clear()
            with self.caplog.at_level("WARNING", logger="dp800.dp800"):
                with pytest.raises(ValueError) as raised:
                    self.driver.connect("TCPIP::example::INSTR")
            assert self.caplog.records
        assert raised.value is error
        assert self.resource.closed == 1
        self.manager.close.assert_not_called()

    def test_non_message_resource_is_closed(self):
        resource = MagicMock(spec=Resource)
        self.manager.open_resource.return_value = resource
        with pytest.raises(TypeError):
            self.connect()
        resource.close.assert_called_once_with()
        assert self.driver._instr is None

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
        assert self.driver._instr is self.resource

    def test_disconnect_attempts_all_commands_and_closes_after_io_failure(self):
        self.connect()
        error = OSError("Output disable failed")
        self.resource.write_errors[":OUTP  CH1,OFF"] = error
        self.resource.write_errors[":SYST:LOC"] = OSError("Local mode failed")
        self.resource.close_error = OSError("Close failed")
        self.caplog.clear()
        with self.caplog.at_level("WARNING", logger="dp800.dp800"):
            with pytest.raises(OSError) as raised:
                self.driver.disconnect()
        assert self.caplog.records
        command_log = next(
            (
                record
                for record in self.caplog.records
                if "Additional disconnect error" in record.getMessage()
            )
        )
        assert ":SYST:LOC" in command_log.getMessage()
        assert command_log.exc_info[1] is self.resource.write_errors[":SYST:LOC"]
        assert raised.value is error
        assert ":OUTP  CH3,OFF" in self.resource.commands
        assert ":SYST:LOC" in self.resource.commands
        assert self.resource.closed == 1
        assert self.driver._instr is None
        self.manager.close.assert_not_called()
        self.driver.disconnect()

    def test_resource_close_failure_clears_state_without_closing_manager(self):
        with patch.object(pyvisa, "ResourceManager", return_value=self.manager):
            self.driver.connect("TCPIP::example::INSTR")
        self.resource.close_error = OSError("Close failed")
        with pytest.raises(OSError):
            self.driver.disconnect()
        self.manager.close.assert_not_called()
        assert self.driver._instr is None

    def test_disconnected_io_raises_clear_error(self):
        with pytest.raises(RuntimeError, match="not connected"):
            self.driver.identity
        with pytest.raises(RuntimeError, match="not connected"):
            self.driver.set_voltage(1)

    def test_identity_and_connection_logging_are_caller_responsibilities(self):
        with patch("dp800.dp800.logger.info") as log_info:
            self.connect()
        log_info.assert_not_called()
        assert self.resource.commands == []
        assert self.driver.identity == ["RIGOL", "DP832", "serial", "version"]
        assert self.resource.commands == ["*IDN?"]
        with patch("virtual_dp800.virtual_dp800.logger.info") as virtual_log_info:
            VirtualDP800().connect("virtual")
        virtual_log_info.assert_not_called()

    def test_connect_only_reads_and_clears_stale_errors(self):
        self.resource.queued_errors = ['-113,"Old error"', '-222,"Another old error"']
        self.connect()
        assert self.resource.io_events == [":SYST:ERR?", ":SYST:ERR?", ":SYST:ERR?"]
        assert self.resource.queued_errors == []
        assert self.driver._instr is self.resource
        self.resource.responses[":MEAS?"] = "1.2"
        assert self.driver.measure() == "1.2"
