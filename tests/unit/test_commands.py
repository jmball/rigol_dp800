# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
import pyvisa
from dp800 import InstrumentError


class TestCommands:

    @pytest.fixture(autouse=True)
    def setup(self, fake_visa, caplog):
        self.driver, self.resource, self.manager = fake_visa
        self.caplog = caplog

    def connect(self, **kwargs):
        self.driver.connect(
            "TCPIP::example::INSTR", resource_manager=self.manager, **kwargs
        )

    def test_io_wrappers_preserve_visa_return_values_and_exceptions(self):
        self.connect()
        assert self.driver._write("*CLS") == len("*CLS")
        self.resource.responses[":MEAS?"] = "  1.200\n"
        assert self.driver._query(":MEAS?") == "  1.200\n"
        error = pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout)
        self.resource.write_errors["*CLS"] = error
        self.resource.query_error = error
        for operation, command in (
            (self.driver._write, "*CLS"),
            (self.driver._query, ":MEAS?"),
        ):
            with pytest.raises(pyvisa.errors.VisaIOError) as raised:
                operation(command)
            assert raised.value is error

    def test_common_command_property_setters_and_validation(self):
        self.connect()
        for name, command, values in (
            ("standard_event_enable_register", "*ESE", (0, 10, 255)),
            ("status_byte_enable_register", "*SRE", (0, 32, 255)),
            ("power_on_status_clear_bit", "*PSC", (0, 1)),
        ):
            for value in values:
                setattr(self.driver, name, value)
                assert self.resource.commands[-1] == f"{command} {value}"
            if command != "*PSC":
                before = list(self.resource.commands)
                for value in (-1, 256):
                    with pytest.raises(ValueError):
                        setattr(self.driver, name, value)
                assert self.resource.commands == before
            self.driver.disconnect()
            with pytest.raises(RuntimeError, match="not connected"):
                setattr(self.driver, name, 1)
            self.connect()

    def test_event_register_and_opc_remain_explicit_methods(self):
        self.connect()
        self.resource.responses.update({"*ESR?": "20", "*OPC?": "1"})
        assert self.driver.get_standard_event_register() == 20
        self.driver.set_opc()
        assert self.driver.get_opc() == 1
        assert self.resource.commands[-3:] == ["*ESR?", "*OPC", "*OPC?"]

    def test_selected_channel_and_implicit_channel_commands(self):
        self.connect()
        self.driver.selected_channel = 2
        self.driver.set_voltage(5.0)
        self.driver.set_voltage(3.0, channel=1)
        assert self.resource.commands[-3:] == [
            ":INST CH2",
            ":VOLT 5.0",
            ":SOUR1:VOLT 3.0",
        ]

    def test_output_enable_queries_state_for_implicit_and_explicit_channels(self):
        self.connect()
        for channel in (None, 1, 2, 3):
            command = ":OUTP?" if channel is None else f":OUTP? CH{channel}"
            for response, expected in (("ON", True), ("OFF", False)):
                self.resource.responses[command] = response
                assert self.driver.get_output_enable(channel) is expected
                assert self.resource.commands[-1] == command

    def test_remote_mode_is_explicit_and_checks_instrument_errors(self):
        self.resource.queued_errors = ['-113,"Stale error"']
        self.resource.errors_after_write[":SYST:REM"] = ['-222,"Remote mode rejected"']
        self.connect()
        assert ":SYST:REM" not in self.resource.commands
        with pytest.raises(InstrumentError) as raised:
            self.driver.set_remote()
        assert str(raised.value) == '-222,"Remote mode rejected"'
        assert self.resource.closed == 0
        assert self.driver._instr is self.resource
