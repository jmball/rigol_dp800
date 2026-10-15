# SPDX-License-Identifier: GPL-3.0-or-later

"""Stateful, deterministic DP800 interface without VISA backends or physical I/O.

The hardware API is inherited so command construction and response parsing stay
identical. The small in-memory transport below supports the commands emitted by
that API; it is not a general-purpose SCPI server or a real-time circuit model.
"""

from __future__ import annotations

import copy
import logging
import math
import ntpath
import statistics
import warnings
from typing import Any, NoReturn

import pyvisa
from pyvisa.resources import MessageBasedResource

from dp800.dp800 import (
    DP800 as HardwareDP800,
    InstrumentError,
    _protocol_settings,
    _fields,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Values are response strings so the public hardware response parsers are reused.
_DEFAULTS: dict[str, str] = {
    ":ANAL:CURRT": "1",
    ":ANAL:STARTT": "1",
    ":ANAL:ENDT": "1",
    ":ANAL:OBJ": "V",
    ":ANAL:FILE": "NONE",
    ":DELAY": "OFF",
    ":DELAY:STAT:GEN": "01P",
    ":DELAY:STOP": "NONE",
    ":DELAY:TIME:GEN": "FIX,1,1",
    ":DISP:MODE": "NORMAL",
    ":DISP": "ON",
    ":DISP:TEXT": '""',
    ":MMEM:CDIR": "D:\\",
    ":MMEM:CAT": "",
    ":MMEM:DISK": "D:\\",
    ":MONI:VOLT": "0",
    ":MONI:VOLT:COND": "NONE,NONE",
    ":MONI:CURR": "0",
    ":MONI:CURR:COND": "NONE,NONE",
    ":MONI:POWER": "0",
    ":MONI:POWER:COND": "NONE",
    ":MONI": "OFF",
    ":MONI:STOP": "OFF,OFF,OFF",
    ":OUTP:RANG": "20V/10A",
    ":PRES:KEY": "DEFAULT",
    ":REC": "OFF",
    ":REC:PERI": "1",
    ":REC:DEST": "NONE",
    ":STAT:QUES:COND": "0",
    ":STAT:QUES:ENAB": "0",
    ":STAT:QUES:INST:ENAB": "0",
    ":SYST:BEEP": "ON",
    ":SYST:BRIG": "50",
    ":SYST:CONT": "50",
    ":SYST:COMM:GPIB:ADDR": "1",
    ":SYST:COMM:LAN:AUTO": "ON",
    ":SYST:COMM:LAN:DHCP": "ON",
    ":SYST:COMM:LAN:DNS": "0.0.0.0",
    ":SYST:COMM:LAN:GATE": "0.0.0.0",
    ":SYST:COMM:LAN:IPAD": "192.0.2.1",
    ":SYST:COMM:LAN:MAC": "00-00-00-00-00-01",
    ":SYST:COMM:LAN:MAN": "OFF",
    ":SYST:COMM:LAN:SMASK": "255.255.255.0",
    ":SYST:COMM:RS232:BAUD": "9600",
    ":SYST:COMM:RS232:DATAB": "8",
    ":SYST:COMM:RS232:FLOWC": "OFF",
    ":SYST:COMM:RS232:PARI": "NONE",
    ":SYST:COMM:RS232:STOPB": "1",
    ":SYST:LANG:TYPE": "English",
    ":SYST:LOCK": "OFF",
    ":SYST:ONOFFS": "OFF",
    ":SYST:OTP": "OFF",
    ":SYST:POWE": "DEFAULT",
    ":SYST:SAV": "OFF",
    ":SYST:TRACKM": "SYNC",
    ":SYST:VERS": "1999.0",
    ":SYST:SELF:TEST:FAN": "PASS",
    ":TIME:CYCLE": "N,1",
    ":TIME:ENDS": "OFF",
    ":TIME:GROUP": "1",
    ":TIME": "OFF",
    ":TIME:TEMP:SEL": "SINE",
    ":TIME:TEMP:OBJ": "V,0.1",
    ":TIME:TEMP:MAXV": "1",
    ":TIME:TEMP:MINV": "0",
    ":TIME:TEMP:INVE": "OFF",
    ":TIME:TEMP:FALLR": "0",
    ":TIME:TEMP:RISER": "0",
    ":TIME:TEMP:INTE": "1",
    ":TIME:TEMP:PERI": "10",
    ":TIME:TEMP:POINT": "10",
    ":TIME:TEMP:SYMM": "50",
    ":TIME:TEMP:WIDT": "1",
    ":TRIG:SOUR": "BUS",
    ":TRIG:DEL": "0",
}
_RANGES = {
    "DP811": [(20.0, 10.0)],
    "DP813": [(8.0, 20.0)],
    "DP821": [(60.0, 1.0), (8.0, 10.0)],
    "DP822": [(20.0, 5.0), (5.0, 16.0)],
    "DP831": [(8.0, 5.0), (30.0, 2.0), (-30.0, 2.0)],
    "DP832": [(30.0, 3.0), (30.0, 3.0), (5.0, 3.0)],
}


class DP800(HardwareDP800):
    """An in-memory supply using the same public API as the hardware driver.

    Measurements use ideal DC behavior: an open circuit draws zero current; an
    optional resistive load produces CV/CC operation. Settings and saved files
    survive disconnect/reconnect. Reset restores operating settings and leaves
    saved files intact. Timers, digital I/O and communication settings are stored
    without background execution or external I/O. Recordings capture one sample
    when started and one when stopped. No VISA manager or OS files are opened.

    Parameters
    ----------
    check_errors : bool, optional
        Raise queued instrument errors after commands, default True.
    model : str, optional
        DP800 model, default DP832A. Physical channel limits follow this model.
    serial_number : str, optional
        Serial number returned by identity, default VIRTUAL0001.
    load_resistance : float or None, optional
        Positive load resistance in ohms for each output; None means open circuit.
    """

    def __init__(
        self,
        check_errors: bool = True,
        *,
        model: str = "DP832A",
        serial_number: str = "VIRTUAL0001",
        load_resistance: float | None = None,
    ) -> None:
        """Initialize isolated state without opening a VISA session."""
        super().__init__()
        if model.upper().removesuffix("A") not in _RANGES:
            raise ValueError("Unsupported DP800 model.")
        if load_resistance is not None and (
            not math.isfinite(load_resistance) or load_resistance <= 0
        ):
            raise ValueError("load_resistance must be finite and positive.")
        if any(char in serial_number for char in ",;\r\n"):
            raise ValueError("Invalid serial number.")
        self._automatic_error_checks = check_errors
        self._virtual = _VirtualResource(model.upper(), serial_number, load_resistance)

    @property
    def _connected(self) -> bool:
        """Whether this virtual driver currently has a connection."""
        return self._instr is not None

    def connect(
        self,
        resource_name: str,
        *,
        resource_manager: pyvisa.ResourceManager | None = None,
        **resource_kwargs: Any,
    ) -> None:
        """Connect to the in-memory supply without creating or using a manager.

        Parameters
        ----------
        resource_name : str
            Accepted for API parity; no address is contacted.
        resource_manager : pyvisa.ResourceManager or None, optional
            Accepted but never used or closed.
        resource_kwargs : dict
            Accepted VISA options. Framing conflicts warn as on the real driver;
            other options do not affect the deterministic virtual transport.
        """
        if self._instr is not None:
            raise RuntimeError("Already connected; disconnect before reconnecting.")
        for key, required in _protocol_settings(resource_name).items():
            if key in resource_kwargs and resource_kwargs[key] != required:
                warnings.warn(
                    f"The driver owns {key}; the supplied value {resource_kwargs[key]!r} will be ignored. Using {required!r}.",
                    stacklevel=2,
                )
        self._instr = self._virtual
        self.get_errors()

    def disconnect(self) -> None:
        """Disable physical outputs, stop running functions and disconnect.

        Repeated calls are harmless. Operating settings and in-memory files remain
        available on reconnect; output states are never restored automatically.
        """
        if self._instr is None:
            return
        for state in self._virtual.channels.values():
            state[":OUTP"] = "OFF"
            state[":TIME"] = state[":DELAY"] = state[":MONI"] = "OFF"
        self._virtual.remote = False
        self._instr = None

    def _check_errors(self) -> None:
        """Honor the optional automatic error-checking flag."""
        if self._automatic_error_checks:
            super()._check_errors()


class _VirtualResource(MessageBasedResource):
    """A synchronous, in-memory transport for the public driver's command subset."""

    def __init__(self, model: str, serial: str, resistance: float | None) -> None:
        # Do not initialize Resource: that would require a real VISA manager.
        """Initialize isolated state without opening a VISA session."""
        self._session = None
        self.model, self.serial, self.resistance = model, serial, resistance
        self.base_model = model.removesuffix("A")
        self.ranges = list(_RANGES[self.base_model])
        self.files: dict[tuple[str, int], dict[str, Any]] = {}
        self.external: dict[str, dict[str, Any]] = {}
        self.directories = {ntpath.normpath("D:/")}
        self.errors: list[str] = []
        self.reset()

    def reset(self) -> None:
        """Restore operating defaults while preserving saved in-memory files."""
        self.ranges = list(_RANGES[self.base_model])
        self.values = dict(_DEFAULTS)
        self.values.update(
            {
                "*ESE": "0",
                "*SRE": "0",
                "*PSC": "1",
                ":SYST:KLOC:STAT": "OFF",
                ":INST:COUP": "NONE",
            }
        )
        self.selected = 1
        self.remote = False
        self.event = 0
        self.questionable_event = 0
        self.instrument_event = 0
        self.instrument_condition = 0
        self.root_condition = 0
        self.conditions = dict.fromkeys(range(1, len(self.ranges) + 1), 0)
        self.channel_events = {number: 0 for number in range(1, len(self.ranges) + 1)}
        self.channels: dict[int, dict[str, str]] = {}
        self.timer_entries: dict[int, dict[int, tuple[float, float, float]]] = {}
        self.delay_entries: dict[int, dict[int, tuple[bool, int]]] = {}
        for number, (voltage, current) in enumerate(self.ranges, 1):
            state = dict(_DEFAULTS)
            state.update({":DELAY:GROUP": "1", ":DELAY:ENDS": "LAST"})
            state.update(
                {
                    ":VOLT": "0",
                    ":CURR": "0",
                    ":VOLT:STEP": "0.001",
                    ":CURR:STEP": "0.001",
                    ":VOLT:TRIG": "0",
                    ":CURR:TRIG": "0.1",
                    ":OUTP": "OFF",
                    ":OUTP:OCP": "OFF",
                    ":OUTP:OVP": "OFF",
                    ":OUTP:OCP:VAL": str(current),
                    ":OUTP:OVP:VAL": str(voltage * 1.1),
                    ":OUTP:OCP:ALAR": "NO",
                    ":OUTP:OVP:ALAR": "NO",
                    ":OUTP:SENS": "OFF",
                    ":OUTP:TRAC": "OFF",
                    ":DELAY:CYCLE": "N,1",
                    ":TIME:CYCLE": "N,1",
                    ":STAT:ENAB": "0",
                    ":MONI:STOP": "OFF,OFF,OFF",
                }
            )
            self.channels[number] = state
            self.timer_entries[number] = {}
            self.delay_entries[number] = {}
        self.presets = {
            (index, number): self._preset_default()
            for index in range(1, 5)
            for number in self.channels
        }
        self.preset_edits = copy.deepcopy(self.presets)
        self.digital: dict[tuple[str, int], str] = {}
        self.keys: dict[str, str] = {}
        self.samples: list[tuple[float, float, float]] = []
        self.recording: dict[str, Any] | None = None
        self.opened: dict[str, Any] | None = None
        self.analysis = ""
        self.armed = False

    def close(self) -> None:
        # The virtual driver's persistent state remains available for reconnect.
        pass

    @staticmethod
    def _preset_default() -> dict[str, str]:
        """Build independent default preset values."""
        return {
            "VOLT": "1",
            "CURR": "0.1",
            "OCP": "OFF,1",
            "OVP": "OFF,30",
            "OTP": "OFF",
            "TRAC": "OFF",
        }

    def _fail(self, message: str, code: int = -222) -> NoReturn:
        """Report an instrument-style error for the consuming queue."""
        raise InstrumentError(f'{code},"{message}"')

    def _channel(self, number: int) -> dict[str, str]:
        """Find a physical channel or report an instrument error."""
        if number not in self.channels:
            self._fail("Invalid channel")
        return self.channels[number]

    def _snapshot(self) -> dict[str, Any]:
        """Copy the operating configuration for state-file storage."""
        return copy.deepcopy(
            {
                "type": "RSF",
                "values": self.values,
                "channels": self.channels,
                "timer": self.timer_entries,
                "delay": self.delay_entries,
                "selected": self.selected,
            }
        )

    def _restore(self, snapshot: dict[str, Any]) -> None:
        """Restore a copied state, timer or delay file."""
        snapshot = copy.deepcopy(snapshot)
        if snapshot["type"] == "RSF":
            self.values, self.channels = snapshot["values"], snapshot["channels"]
            self.timer_entries, self.delay_entries = (
                snapshot["timer"],
                snapshot["delay"],
            )
            self.selected = snapshot["selected"]
        elif snapshot["type"] == "RTF":
            self.timer_entries[self.selected] = snapshot["entries"]
        elif snapshot["type"] == "RDF":
            self.delay_entries[self.selected] = snapshot["entries"]
        else:
            self._fail("File cannot be recalled")

    def _save(self, kind: str) -> dict[str, Any]:
        """Build a typed file snapshot for the current channel."""
        if kind == "RSF":
            return self._snapshot()
        if kind not in ("RTF", "RDF"):
            self._fail("Invalid file type")
        entries = self.timer_entries if kind == "RTF" else self.delay_entries
        return {
            "type": kind,
            "entries": copy.deepcopy(entries[self.selected]),
            "locked": False,
        }

    def _path(self, path: str) -> str:
        """Resolve an external instrument path without accessing the host."""
        return ntpath.normpath(ntpath.join(self.values[":MMEM:CDIR"], path))

    def _sample(self, number: int) -> tuple[float, float, float]:
        """Compute ideal DC readings and apply protection/monitor responses."""
        state = self._channel(number)
        if state[":OUTP"] == "OFF":
            self._update_status(number)
            return 0.0, 0.0, 0.0
        voltage = float(state[":VOLT"])
        current = (
            0.0
            if self.resistance is None
            else min(abs(voltage) / self.resistance, float(state[":CURR"]))
        )
        if self.resistance is not None:
            voltage = math.copysign(
                min(abs(voltage), current * self.resistance), voltage
            )
        for protection, quantity in (("OCP", current), ("OVP", abs(voltage))):
            if state[f":OUTP:{protection}"] == "ON" and quantity > abs(
                float(state[f":OUTP:{protection}:VAL"])
            ):
                state[f":OUTP:{protection}:ALAR"] = "YES"
                state[":OUTP"] = "OFF"
                self._update_status(number)
                return 0.0, 0.0, 0.0
        if state[":MONI"] == "ON":
            predicates: list[tuple[bool, str]] = []
            for monitored_quantity, measured in (
                ("VOLT", abs(voltage)),
                ("CURR", current),
                ("POWER", abs(voltage) * current),
            ):
                fields = state[f":MONI:{monitored_quantity}:COND"].split(",")
                if fields[0] != "NONE":
                    threshold = float(state[f":MONI:{monitored_quantity}"])
                    matched = (
                        measured < threshold
                        if fields[0].startswith("<")
                        else measured > threshold
                    )
                    predicates.append(
                        (matched, fields[1] if len(fields) > 1 else "NONE")
                    )
            if predicates:
                matched = predicates[0][0]
                for index in range(1, len(predicates)):
                    matched = (
                        matched and predicates[index][0]
                        if predicates[index - 1][1] == "AND"
                        else matched or predicates[index][0]
                    )
                if matched and state[":MONI:STOP"].split(",")[0] == "ON":
                    state[":OUTP"] = "OFF"
                    self._update_status(number)
                    return 0.0, 0.0, 0.0
        self._update_status(number)
        return voltage, current, abs(voltage) * current

    def _bound(self, header: str, number: int, upper: bool) -> float:
        """Return approximate model-specific limits used by virtual queries."""
        voltage, current = self.ranges[number - 1]
        if not upper:
            return (
                voltage
                if voltage < 0 and ("VOLT" in header or "OVP" in header)
                else 0.0
            )
        if "CURR" in header or "OCP" in header:
            return current * (1.1 if "OCP" in header else 1)
        if "VOLT" in header or "OVP" in header or "MAXV" in header or "MINV" in header:
            return max(0.0, voltage * (1.1 if "OVP" in header else 1))
        if header.startswith(":MONI:POWER"):
            return abs(voltage * current)
        if header in (":SYST:BRIG", ":SYST:CONT"):
            return 100.0
        if header == ":TRIG:DEL":
            return 3600.0
        return 99999.0

    def _numeric(self, value: str, header: str, number: int) -> str:
        """Resolve symbolic setpoints and reject invalid numeric settings."""
        state = self._channel(number)
        value = value.upper()
        if value in ("MIN", "MAX"):
            return str(self._bound(header, number, value == "MAX"))
        if value in ("UP", "DOWN"):
            return str(
                float(state[header])
                + (1 if value == "UP" else -1) * float(state[header + ":STEP"])
            )
        if value == "DEF":
            return "0.001"
        result = float(value)
        if not math.isfinite(result):
            self._fail("Invalid numeric value")
        if header in (":VOLT", ":CURR", ":VOLT:TRIG", ":CURR:TRIG"):
            low, high = self._bound(header, number, False), self._bound(
                header, number, True
            )
            if not low <= result <= high:
                self._fail("Setpoint out of range")
        return str(result)

    def write(
        self, message: str, termination: str | None = None, encoding: str | None = None
    ) -> int:
        """Execute one driver write and queue any instrument-style error."""
        try:
            self._execute(message, False)
        except (InstrumentError, ValueError, KeyError, IndexError) as error:
            self.errors.append(
                str(error)
                if isinstance(error, InstrumentError)
                else '-222,"Invalid parameter"'
            )
            self.event |= 32
        return len(message)

    def query(self, message: str, delay: float | None = None) -> str:
        """Return one response, retaining errors for the normal queue check."""
        if message.strip().upper() == ":SYST:ERR?":
            return self.errors.pop(0) if self.errors else '0,"No error"'
        try:
            return self._execute(message, True)
        except (InstrumentError, ValueError, KeyError, IndexError) as error:
            self.errors.append(
                str(error)
                if isinstance(error, InstrumentError)
                else '-222,"Invalid parameter"'
            )
            self.event |= 32
            return ""

    def _execute(self, message: str, query: bool) -> str:
        """Dispatch the command subset emitted by the public hardware API."""
        head, _, tail = message.strip().partition(" ")
        head = head.upper().removesuffix("?")
        args = _fields(tail) if tail else []
        number = self.selected
        if head.startswith(":SOUR"):
            source, _, suffix = head[1:].partition(":")
            number = int(source[4:])
            head = ":" + suffix
        if head.startswith(":OUTP") and args and args[0].upper().startswith("CH"):
            number = int(args.pop(0)[2:])
        state = self._channel(number)
        scoped = head.startswith(
            (":DELAY", ":TIME", ":MONI", ":TRIG:DEL", ":TRIG:SOUR")
        )
        values = (
            state
            if scoped or head.startswith((":CURR", ":VOLT", ":OUTP"))
            else self.values
        )
        if head == "*IDN":
            return f"RIGOL,{self.model},{self.serial},VIRTUAL"
        if head == "*OPT":
            return "DP8-ACCURACY,DP8-ANALYZER,DP8-MONITOR,DP8-LAN,DP8-RS232,DP8-TRIGGER"
        if head == "*TST":
            return "TopBoard:PASS,BottomBoard:PASS,Fan:PASS"
        if head == "*RST":
            self.reset()
            self.errors.clear()
            return ""
        if head == "*CLS":
            self.event = self.questionable_event = self.instrument_event = 0
            self.channel_events = dict.fromkeys(self.channels, 0)
            self.errors.clear()
            return ""
        if head == "*OPC":
            if not query:
                self.event |= 1
            return "1"
        if head == "*ESR":
            result, self.event = self.event, 0
            return str(result)
        if head == "*STB":
            return str(
                (32 if self.event & int(self.values["*ESE"]) else 0)
                | (4 if self.errors else 0)
            )
        if head in ("*WAI", ":SYST:BEEP:IMM", ":SYST:COMM:LAN:APPL"):
            return ""
        if head in ("*TRG", ":INIT"):
            if head == ":INIT":
                self.armed = True
            if self.armed and (head == "*TRG" or state[":TRIG:SOUR"] == "IMM"):
                targets = {number}
                coupling = self.values[":INST:COUP"]
                if coupling == "ALL":
                    targets.update(self.channels)
                elif coupling != "NONE":
                    targets.update(int(token[2:]) for token in coupling.split(","))
                for target in targets:
                    target_state = self._channel(target)
                    target_state[":VOLT"], target_state[":CURR"] = (
                        target_state[":VOLT:TRIG"],
                        target_state[":CURR:TRIG"],
                    )
                    self._sample(target)
                self.armed = False
            return ""
        if head in (":SYST:REM", ":SYST:LOC"):
            self.remote = head.endswith("REM")
            return ""
        if head == ":SYST:SELF:TEST:TEMP":
            return "25.0"
        if head == ":SYST:SELF:TEST:BOARD":
            return "PASS" if args else "PASS,PASS"
        if head == ":INST":
            candidate = int(args[0][2:])
            self._channel(candidate)
            self.selected = candidate
            return ""
        if head == ":INST:NSEL":
            return str(self.selected)
        if head == ":INST:COUP" and query:
            coupling = self.values[head]
            if coupling in ("ALL", "NONE"):
                return coupling
            return ",".join(
                f"{item}:{self._rating(int(item[2:]))}" for item in coupling.split(",")
            )
        if head == ":APPL":
            if args and args[0].startswith("CH"):
                number = int(args.pop(0)[2:])
                state = self._channel(number)
            if query:
                if args:
                    return state[":" + args[0]]
                return f"CH{number},{self._rating(number)},{state[':VOLT']},{state[':CURR']}"
            for header, value in zip((":VOLT", ":CURR"), args):
                state[header] = self._numeric(value, header, number)
            self.selected = number
            return ""
        if head.startswith(":MEAS"):
            if args:
                number = int(args[0][2:])
            sample = self._sample(number)
            quantity = head.removeprefix(":MEAS").strip(":")
            return (
                ",".join(map(str, sample))
                if quantity == "ALL"
                else str(sample[{"": 0, "VOLT": 0, "CURR": 1, "POWE": 2}[quantity]])
            )
        if head == ":OUTP:MODE":
            voltage, current, _ = self._sample(number)
            return (
                "CC"
                if state[":OUTP"] == "ON"
                and self.resistance is not None
                and abs(float(state[":VOLT"])) / self.resistance > float(state[":CURR"])
                else "CV"
            )
        if head in (":OUTP:SENS", ":OUTP:TRAC"):
            sense = self.base_model in ("DP811", "DP813") or (
                self.base_model in ("DP821", "DP822") and number == 2
            )
            tracking = (self.base_model == "DP831" and number in (2, 3)) or (
                self.base_model == "DP832" and number in (1, 2)
            )
            if not (sense if head.endswith("SENS") else tracking):
                if query:
                    return "NONE"
                self._fail("Function unavailable on channel")
        if head in (
            ":CURR:PROT:CLE",
            ":VOLT:PROT:CLE",
            ":OUTP:OCP:CLEAR",
            ":OUTP:OVP:CLEAR",
        ):
            protection = "OCP" if "CURR" in head or "OCP" in head else "OVP"
            state[f":OUTP:{protection}:ALAR"] = "NO"
            if ":PROT:" in head:
                state[":OUTP"] = "ON"
            self._sample(number)
            return ""
        if head == ":OUTP:RANG":
            if len(self.channels) != 1:
                self._fail("Range is only available on single-channel models")
            if not query:
                high = args[0] in ("HIGH", "P40V")
                self.ranges[0] = (
                    (40.0, 5.0)
                    if self.base_model == "DP811" and high
                    else (
                        (20.0, 10.0)
                        if self.base_model == "DP811"
                        else (20.0, 10.0) if high else (8.0, 20.0)
                    )
                )
            return self._rating(1)
        if head == ":DISP:TEXT:CLE":
            self.values[":DISP:TEXT"] = '""'
            return ""
        if head == ":DISP:TEXT" and not query:
            self.values[head] = '"' + args[0].replace('"', '""') + '"'
            return ""
        if head == ":SYST:KLOC":
            if query:
                return self.keys.get(args[0], self.keys.get("ALL", "0"))
            if args[0] == "ALL":
                self.keys.clear()
            self.keys[args[0]] = "1" if args[1] == "ON" else "0"
            return ""
        if head.startswith(":PRES"):
            return self._preset(head, args, query, number)
        if head.startswith(":MEM:") or head in ("*SAV", "*RCL", ":STOR:LOC"):
            return self._memory(head, args, query)
        if head.startswith(":MMEM"):
            return self._external(head, args, query)
        if head.startswith(":REC"):
            return self._recorder(head, args, query, number)
        if head.startswith(":ANAL"):
            return self._analyzer(head, args, query)
        if head in (":TIME:PARA", ":DELAY:PARA"):
            entries = (
                self.timer_entries[number]
                if head.startswith(":TIME")
                else self.delay_entries[number]
            )
            first = int(args[0])
            if query:
                count = int(args[1]) if len(args) > 1 else 1
                rows = []
                for index in range(first, first + count):
                    entry = entries.get(
                        index,
                        (
                            (1.0, 0.1, 1.0)
                            if head.startswith(":TIME")
                            else (bool(index % 2), 1)
                        ),
                    )
                    rows.append(
                        f"{index},"
                        + ",".join(
                            (
                                ("ON" if item else "OFF")
                                if isinstance(item, bool)
                                else str(item)
                            )
                            for item in entry
                        )
                        + ";"
                    )
                payload = "".join(rows)
                return f"#9{len(payload):09d}{payload}"
            if not 0 <= first <= 2047:
                self._fail("Entry index out of range")
            if head.startswith(":TIME"):
                voltage, current, duration = (float(value) for value in args[1:])
                self.timer_entries[number][first] = (voltage, current, duration)
            else:
                self.delay_entries[number][first] = (args[1] == "ON", int(args[2]))
            return ""
        if head == ":TIME:TEMP:CONST":
            self._construct_template(number)
            return ""
        if head == ":MONI:STOP":
            if not query:
                actions = state[head].split(",")
                if args[0] == "NONE":
                    actions = ["OFF"] * 3
                else:
                    actions[{"OUTOFF": 0, "WARN": 1, "BEEPER": 2}[args[0]]] = args[1]
                state[head] = ",".join(actions)
            return state[head]
        if head.startswith(":TRIG:IN") or head.startswith(":TRIG:OUT"):
            return self._digital(head, args, query)
        if head.startswith(":STAT:QUES"):
            return self._status(head, args, query)
        if head == ":LIC:SET":
            if len(args[0]) != 28 or not args[0].isascii() or not args[0].isalnum():
                self._fail("Invalid option license")
            return ""
        if head in values:
            if not query and head in (":TIME", ":DELAY") and args == ["ON"]:
                other_function = ":DELAY" if head == ":TIME" else ":TIME"
                if state[other_function] == "ON":
                    self._fail("Timer and delayer cannot run together")
            if query:
                if args and args[-1] in ("MIN", "MAX", "DEF"):
                    return (
                        "0.001"
                        if args[-1] == "DEF"
                        else str(self._bound(head, number, args[-1] == "MAX"))
                    )
                return values[head]
            if head in (
                ":VOLT",
                ":CURR",
                ":VOLT:STEP",
                ":CURR:STEP",
                ":VOLT:TRIG",
                ":CURR:TRIG",
                ":OUTP:OCP:VAL",
                ":OUTP:OVP:VAL",
            ):
                values[head] = self._numeric(args[0], head, number)
            else:
                values[head] = ",".join(args)
                if head in (":TIME:CYCLE", ":DELAY:CYCLE") and args == ["N"]:
                    values[head] = "N,1"
                if head in (
                    ":SYST:BRIG",
                    ":SYST:CONT",
                    ":MONI:VOLT",
                    ":MONI:CURR",
                    ":MONI:POWER",
                    ":TIME:TEMP:MAXV",
                    ":TIME:TEMP:MINV",
                    ":TRIG:DEL",
                ):
                    values[head] = self._numeric(args[0], head, number)
                    if head in (":SYST:BRIG", ":SYST:CONT"):
                        values[head] = str(int(float(values[head])))
                if head == ":SYST:LANG:TYPE":
                    values[head] = {
                        "EN": "English",
                        "CH": "Chinese",
                        "JAP": "Japanese",
                        "KOR": "Korean",
                        "GER": "German",
                        "POR": "Portuguese",
                        "POL": "Polish",
                        "CHT": "Traditional Chinese",
                        "RUS": "Russian",
                    }.get(args[0], args[0])
                if head == ":SYST:POWE" and args[0] == "DEF":
                    values[head] = "DEFAULT"
            if head in (
                ":VOLT",
                ":CURR",
                ":OUTP",
                ":OUTP:OCP:VAL",
                ":OUTP:OVP:VAL",
                ":OUTP:OCP",
                ":OUTP:OVP",
                ":MONI",
            ):
                self._sample(number)
            if head == ":OUTP" and self.values[":SYST:ONOFFS"] == "ON":
                for other in self.channels.values():
                    other[head] = args[0]
            pair = (2, 3) if self.base_model == "DP831" else (1, 2)
            if self.base_model in ("DP831", "DP832") and number in pair:
                other_number = pair[1] if number == pair[0] else pair[0]
                other_state = self.channels[other_number]
                if head == ":OUTP:TRAC" and self.values[":SYST:TRACKM"] == "SYNC":
                    other_state[head] = state[head]
                if head == ":VOLT" and state[":OUTP:TRAC"] == "ON":
                    other_state[head] = str(
                        math.copysign(
                            abs(float(state[head])), self.ranges[other_number - 1][0]
                        )
                    )
                    self._sample(other_number)
            if head == ":DELAY:STAT:GEN":
                enabled = args[0] == "10P"
                for index in range(int(state[":DELAY:GROUP"])):
                    _, duration = self.delay_entries[number].get(index, (False, 1))
                    self.delay_entries[number][index] = (
                        enabled ^ bool(index % 2),
                        duration,
                    )
            if head == ":DELAY:TIME:GEN":
                method, base_time, step = (args + ["1", "1"])[0:3]
                for index in range(int(state[":DELAY:GROUP"])):
                    enabled, _ = self.delay_entries[number].get(
                        index, (bool(index % 2), 1)
                    )
                    duration = (
                        int(base_time)
                        if method == "FIX" and enabled
                        else (
                            int(step)
                            if method == "FIX"
                            else int(base_time)
                            + (1 if method == "INC" else -1) * index * int(step)
                        )
                    )
                    self.delay_entries[number][index] = (enabled, max(1, duration))
            return ""
        self._fail("Undefined header", -113)
        return ""

    def _rating(self, number: int) -> str:
        """Format the nominal voltage/current rating of a physical output."""
        voltage, current = self.ranges[number - 1]
        return f"{voltage:g}V/{current:g}A"

    def _preset(self, head: str, args: list[str], query: bool, number: int) -> str:
        """Apply or edit the selected channel in a user preset."""
        if head == ":PRES:KEY":
            if not query:
                self.values[head] = args[0]
            return self.values[head]
        if head == ":PRES":
            key = self.values[":PRES:KEY"]
            preset = (
                self._preset_default()
                if key == "DEFAULT"
                else self.presets[(int(key[4:]), number)]
            )
            state = self.channels[number]
            state[":VOLT"], state[":CURR"] = preset["VOLT"], preset["CURR"]
            for protection in ("OCP", "OVP"):
                enabled, threshold = preset[protection].split(",")
                state[f":OUTP:{protection}"] = enabled
                state[f":OUTP:{protection}:VAL"] = threshold
            self.values[":SYST:OTP"] = preset["OTP"]
            state[":OUTP:TRAC"] = preset["TRAC"]
            self._sample(number)
            return ""
        index = int(head.partition("USER")[2].partition(":")[0])
        setting = head.rsplit(":", 1)[-1]
        if setting == "DEF":
            self.preset_edits[(index, number)] = self._preset_default()
            return ""
        if setting == "SURE":
            self.presets[(index, number)] = copy.deepcopy(
                self.preset_edits[(index, number)]
            )
            return ""
        preset = self.preset_edits[(index, number)]
        if not query:
            if setting in ("OCP", "OVP") and len(args) == 1:
                args.append(preset[setting].split(",")[1])
            if setting in ("CURR", "VOLT"):
                args[0] = self._numeric(args[0], ":" + setting, number)
            if setting in ("OCP", "OVP") and args[-1] in ("MIN", "MAX"):
                args[-1] = str(
                    self._bound(":OUTP:" + setting + ":VAL", number, args[-1] == "MAX")
                )
            preset[setting] = ",".join(args)
        if query and args and args[0] in ("MIN", "MAX"):
            bound = str(self._bound(":" + setting, number, args[0] == "MAX"))
            return (
                preset[setting].split(",")[0] + "," + bound
                if setting in ("OCP", "OVP")
                else bound
            )
        return preset[setting]

    def _memory(self, head: str, args: list[str], query: bool) -> str:
        """Handle typed internal file storage and locking."""
        kind = "RSF" if head in ("*SAV", "*RCL", ":STOR:LOC") else args.pop(0)
        slot = int(args.pop(0))
        if not 1 <= slot <= 10:
            self._fail("Invalid memory slot")
        key = (kind, slot)
        if head.endswith(":VAL"):
            return "YES" if key in self.files else "NO"
        if head.endswith(":LOCK"):
            if query:
                return "YES" if self.files.get(key, {}).get("locked", False) else "NO"
            self.files[key]["locked"] = args[0] == "ON"
            return ""
        if head in ("*RCL", ":MEM:LOAD"):
            self._restore(self.files[key])
            return ""
        if self.files.get(key, {}).get("locked", False):
            self._fail("File is locked")
        if head == ":MEM:DEL":
            del self.files[key]
        else:
            self.files[key] = self._save(kind)
            self.files[key]["name"] = args[0] if args else f"RIGOL{slot}.{kind}"
        return ""

    def _external(self, head: str, args: list[str], query: bool) -> str:
        """Handle instrument paths and files in memory."""
        if head == ":MMEM:DISK":
            return ntpath.normpath("D:/")
        if head == ":MMEM:CAT":
            parent = self.values[":MMEM:CDIR"]
            return ",".join(
                sorted(
                    ntpath.basename(path)
                    for path in set(self.external) | self.directories
                    if path != parent and ntpath.dirname(path) == parent
                )
            )
        path = self._path(args[0]) if args else self.values[":MMEM:CDIR"]
        if head == ":MMEM:CDIR":
            if not query:
                if path not in self.directories:
                    self._fail("Directory does not exist")
                self.values[head] = path
            return self.values[head]
        if head == ":MMEM:MDIR":
            self.directories.add(path)
        elif head == ":MMEM:DEL":
            del self.external[path]
        elif head == ":MMEM:LOAD":
            self._restore(self.external[path])
        elif head == ":MMEM:STOR":
            self.external[path] = self._save(
                ntpath.splitext(path)[1].lstrip(".").upper()
            )
        else:
            self._fail("Undefined header", -113)
        return ""

    def _recorder(self, head: str, args: list[str], query: bool, number: int) -> str:
        """Capture synchronous samples at recording start and stop."""
        if (
            self.values[":REC"] == "ON"
            and not query
            and head in (":REC:MEM", ":REC:MMEM", ":REC:PERI")
        ):
            self._fail("Cannot configure an active recorder")
        if head == ":REC:MEM":
            self.values[":REC:DEST"] = f"C:\\REC{args[0]}:{args[1]}"
            self.recording = {"slot": int(args[0]), "name": args[1]}
        elif head == ":REC:MMEM":
            self.values[":REC:DEST"] = self._path(args[0])
            self.recording = {"path": self._path(args[0])}
        elif head == ":REC" and not query:
            if self.recording is None:
                self._fail("Configure a recording destination first")
            if args[0] == "ON":
                self.samples = [self._sample(number)]
            else:
                self.samples.append(self._sample(number))
                snapshot = {
                    "type": "ROF",
                    "name": self.recording.get("name", "RIGOL.ROF"),
                    "samples": list(self.samples),
                    "period": int(self.values[":REC:PERI"]),
                }
                if "slot" in self.recording:
                    key = ("ROF", self.recording["slot"])
                    if self.files.get(key, {}).get("locked", False):
                        self._fail("File is locked")
                    self.files[key] = snapshot
                else:
                    self.external[self.recording["path"]] = snapshot
            self.values[head] = args[0]
        elif head in self.values:
            if not query:
                self.values[head] = args[0]
            return self.values[head]
        else:
            self._fail("Undefined recorder header", -113)
        return ""

    def _analyzer(self, head: str, args: list[str], query: bool) -> str:
        """Read recordings and compute statistics for the selected interval."""
        if head in (":ANAL:MEM", ":ANAL:MMEM"):
            self.opened = (
                self.files[("ROF", int(args[0]))]
                if head.endswith(":MEM")
                else self.external[self._path(args[0])]
            )
            if self.opened["type"] != "ROF":
                self._fail("Expected a recording")
            record_name = self.opened.get("name", "RIGOL.ROF")
            self.values[":ANAL:FILE"] = (
                f"C:\\REC{args[0]}:{record_name}"
                if head.endswith(":MEM")
                else self._path(args[0])
            )
            self.values[":ANAL:STARTT"] = str(self.opened["period"])
            self.values[":ANAL:ENDT"] = str(
                len(self.opened["samples"]) * self.opened["period"]
            )
            return ""
        if head == ":ANAL:FILE":
            return self.values[head]
        if self.opened is None:
            self._fail("No recording is open")
        if head == ":ANAL:VAL":
            index = int(args[0]) // self.opened["period"] - 1
            if not 0 <= index < len(self.opened["samples"]):
                self._fail("Recording time is out of range")
            sample = self.opened["samples"][index]
            return f"Volt:{sample[0]}V,Curr:{sample[1]}A,Power:{sample[2]}W"
        if head == ":ANAL:ANAL":
            column = {"V": 0, "C": 1, "P": 2}[self.values[":ANAL:OBJ"]]
            first = int(self.values[":ANAL:STARTT"]) // self.opened["period"] - 1
            last = int(self.values[":ANAL:ENDT"]) // self.opened["period"]
            samples = [row[column] for row in self.opened["samples"][first:last]]
            average = statistics.mean(samples)
            result = {
                "Group": len(samples),
                "Median": statistics.median(samples),
                "Mode": statistics.mode(samples),
                "Average": average,
                "Variance": statistics.pvariance(samples),
                "Range": max(samples) - min(samples),
                "Min": min(samples),
                "Max": max(samples),
                "Mean": statistics.mean(abs(value - average) for value in samples),
            }
            self.analysis = ",".join(f"{key}:{value}" for key, value in result.items())
            return ""
        if head == ":ANAL:RES":
            if not self.analysis:
                self._fail("Run analysis first")
            return self.analysis
        if head in self.values:
            period = self.opened["period"]
            end = len(self.opened["samples"]) * period
            if args and args[0] in ("MIN", "MAX"):
                bound = period if args[0] == "MIN" else end
                if query:
                    return str(bound)
                args[0] = str(bound)
            if not query:
                self.values[head] = args[0]
            return self.values[head]
        self._fail("Undefined analyzer header", -113)
        return ""

    def _digital(self, head: str, args: list[str], query: bool) -> str:
        """Retain per-line digital input/output settings."""
        limit = args.pop() if query and args and args[-1] in ("MIN", "MAX") else None
        args = [arg for arg in args if arg]
        line = int(args.pop(0)[1:]) if args and args[0].startswith("D") else 0
        if not 0 <= line <= 3:
            self._fail("Invalid digital line")
        key = (head, line)
        suffix = head.rsplit(":", 1)[-1]
        defaults = {
            "IN": "OFF",
            "OUT": "OFF",
            "RESP": "OFF",
            "SENS": "LOW",
            "TYPE": "RISE",
            "SOUR": "CH1",
            "DUTY": "50",
            "PERI": "0.1",
            "POLA": "POSITIVE",
            "SIGN": "LEVEL",
            "COND": "OUTOFF",
        }
        if not query:
            self.digital[key] = ",".join(args)
        response = self.digital.get(key, defaults[suffix])
        if limit is not None and suffix == "COND":
            condition = response.split(",")[0]
            quantity = {"V": ":VOLT", "C": ":CURR", "P": ":MONI:POWER"}.get(
                condition[-1], ":VOLT"
            )
            response = (
                condition
                + ","
                + str(self._bound(quantity, self.selected, limit == "MAX"))
            )
        return f"D{line},{response}" if query and suffix in ("IN", "OUT") else response

    def _update_status(self, number: int) -> None:
        """Latch rising condition bits without consuming other registers."""
        state = self.channels[number]
        condition = (4 if state[":OUTP:OVP:ALAR"] == "YES" else 0) | (
            8 if state[":OUTP:OCP:ALAR"] == "YES" else 0
        )
        if state[":OUTP"] == "ON":
            cc = self.resistance is not None and abs(
                float(state[":VOLT"])
            ) / self.resistance > float(state[":CURR"])
            condition |= 1 if cc else 2
        self.channel_events[number] |= condition & ~self.conditions[number]
        self.conditions[number] = condition
        instrument = sum(
            1 << channel
            for channel, value in self.channel_events.items()
            if value & int(self.channels[channel][":STAT:ENAB"])
        )
        self.instrument_event |= instrument & ~self.instrument_condition
        self.instrument_condition = instrument
        if len(self.channels) == 1:
            root_condition = (
                (condition & 3)
                | (512 if condition & 4 else 0)
                | (1024 if condition & 8 else 0)
            )
        else:
            root_condition = (
                8192 if instrument & int(self.values[":STAT:QUES:INST:ENAB"]) else 0
            )
        self.questionable_event |= root_condition & ~self.root_condition
        self.root_condition = root_condition

    def _status(self, head: str, args: list[str], query: bool) -> str:
        """Read conditions or consume one independent event register."""
        for number in self.channels:
            self._update_status(number)
        if ":ISUM" in head:
            number = int(head.partition(":ISUM")[2].partition(":")[0])
            state = self._channel(number)
            if head.endswith(":ENAB"):
                if not query:
                    state[":STAT:ENAB"] = args[0]
                return state[":STAT:ENAB"]
            if head.endswith(":COND"):
                return str(self.conditions[number])
            result, self.channel_events[number] = self.channel_events[number], 0
            return str(result)
        if head.endswith(":ENAB"):
            if not query:
                self.values[head] = args[0]
            return self.values[head]
        if head == ":STAT:QUES:INST":
            result, self.instrument_event = self.instrument_event, 0
            return str(result)
        if head.endswith(":COND"):
            if len(self.channels) == 1:
                condition = self.conditions[1]
                return str(
                    (condition & 3)
                    | (512 if condition & 4 else 0)
                    | (1024 if condition & 8 else 0)
                )
            active = sum(
                1 << channel
                for channel, value in self.channel_events.items()
                if value & int(self.channels[channel][":STAT:ENAB"])
            )
            return "8192" if active & int(self.values[":STAT:QUES:INST:ENAB"]) else "0"
        result, self.questionable_event = self.questionable_event, 0
        return str(result)

    def _construct_template(self, number: int) -> None:
        """Generate deterministic approximate timer waveform entries."""
        state = self.channels[number]
        count = int(state[":TIME:TEMP:POINT"])
        low, high = float(state[":TIME:TEMP:MINV"]), float(state[":TIME:TEMP:MAXV"])
        waveform = state[":TIME:TEMP:SEL"]
        object_, fixed = state[":TIME:TEMP:OBJ"].split(",")
        period = int(state[":TIME:TEMP:PERI"])
        for index in range(count):
            phase = (index % period) / period
            if waveform == "SINE":
                fraction = (1 - math.cos(phase * 2 * math.pi)) / 2
            elif waveform == "SQUARE":
                fraction = float(phase < float(state[":TIME:TEMP:WIDT"]) / period)
            elif waveform in ("DN", "FALL"):
                fraction = 1 - index / max(1, count - 1)
            elif waveform == "UPDN":
                fraction = 1 - abs(2 * index / max(1, count - 1) - 1)
            elif waveform == "RAMP":
                symmetry = float(state[":TIME:TEMP:SYMM"]) / 100
                fraction = (
                    phase / symmetry
                    if phase < symmetry
                    else (1 - phase) / (1 - symmetry)
                )
            else:
                fraction = index / max(1, count - 1)
            if state[":TIME:TEMP:INVE"] == "ON":
                fraction = 1 - fraction
            varying = low + (high - low) * fraction
            voltage, current = (
                (varying, float(fixed)) if object_ == "V" else (float(fixed), varying)
            )
            self.timer_entries[number][index] = (
                voltage,
                current,
                float(state[":TIME:TEMP:INTE"]),
            )
        state[":TIME:GROUP"] = str(count)


__all__ = ["DP800"]
