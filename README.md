# rigol_dp800

Python library for controlling Rigol DP800 series power supplies through PyVISA.

## Installation

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
```

For development, use `.venv/bin/python -m pip install -e .` instead.
On Windows, use `.venv\Scripts\python.exe` for the environment's interpreter.
PyVISA and the pure Python `pyvisa-py` backend are installed as dependencies;
hardware access may require additional drivers or backend configuration.

## Channels

```python
from dp800 import DP800

with DP800() as supply:
    supply.connect("TCPIP0::192.0.2.1::INSTR")  # Use your instrument's VISA name.
    ch1 = supply.channels[1]
    ch1.voltage = 5.0
    ch1.current = 0.5
    ch1.output_enabled = True

    print(ch1.channel, ch1.measured_voltage, ch1.measured_current)
    print(ch1.measured_power)
    print(ch1.measure("ALL"))  # Voltage, current, power as response strings.
```

`DP800Channel` objects share the supply's connection and address their physical
channel explicitly, without changing `selected_channel`. `voltage` and `current`
are configured setpoints; `measured_voltage`, `measured_current`, and
`measured_power` return measured values as floats. `measure()` preserves the
parent driver's response types and accepts `"ALL"`.

Channels also expose read-only `output_mode`, `ocp_tripped`, and `ovp_tripped`,
plus read/write `ocp_enabled`, `ocp_value`, `ovp_enabled`, `ovp_value`, and
`sense_enabled`. Protection values use amps for OCP and volts for OVP; assignments
also accept `"MIN"` or `"MAX"`. Call `clear_ocp_label()` or `clear_ovp_label()` to
clear the corresponding alarm label. Sensing support depends on the model and
channel.

`channels` is a read-only mapping containing stable views for channel numbers
1–3. Creating and accessing these views performs no I/O or model discovery.
The instrument determines whether a channel or operation is supported. Channel
objects survive reconnects and address the parent's current connection; using
them while disconnected raises `RuntimeError`. Exiting the context manager
disconnects and attempts to disable all three outputs.

The virtual driver exposes three channels using the same class, with its
existing fixed placeholder values and no-op setters. Its `measure()` continues
to return `0.0`, including for `"ALL"`.

## Instrument errors

`connect()` drains stale errors before entering remote mode, then checks remote
mode for errors. Each successful write and each successfully read query response
is followed by draining `:SYST:ERR?`. Nonzero entries raise `InstrumentError`,
which exposes the associated `command` and an `errors` tuple of code/message
pairs. Checks consume the queue and add communication round trips. A command
may have executed even if its subsequent error check fails. Queue draining is
limited to 100 reads.

When a query raises a VISA timeout, the driver attempts error diagnostics with
a best-effort 500 ms time budget and restores the original resource timeout.
Reported instrument errors raise `InstrumentError` with the original timeout
as its cause. Empty, malformed, or failed diagnostics re-raise the original
timeout. This fallback neither retries the command nor guarantees response
synchronization: a late original response can interfere with diagnostics, and
the caller may need to reconnect before continuing.

`get_error()` directly reads one error entry without automatic checking. The
virtual driver returns `(0, "No error")` and performs no diagnostic I/O.

## Building distributions

```sh
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

This creates a source distribution and wheel in `dist/`. Package metadata,
dependencies, package discovery, and the build backend are defined in
`pyproject.toml`.
