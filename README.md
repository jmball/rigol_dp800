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
1–3. Mapping entries cannot be replaced; the channel instances themselves expose
read/write settings. Creating and accessing these views performs no I/O or model discovery.
The instrument determines whether a channel or operation is supported. Channel
objects survive reconnects and address the parent's current connection; using
them while disconnected raises `RuntimeError`. Exiting the context manager
disconnects and disables the model's physical outputs. Shutdown reads identity
to choose those outputs, without retaining a channel count.

Both drivers now expose the complete command families from the programming guide:
analyzer, delay/timer, display, storage, monitor, presets, recording, status,
communications and digital triggering. Scalar settings use properties; operations
with channel, line, preset or entry arguments remain methods. See the
[interface reference](docs/driver-interface.md) for names, return types, command
equivalents and changes from the unfinished API.

The virtual driver is stateful and shares the hardware driver's public API and
return types. Settings, presets and in-memory files round-trip. Optional
`load_resistance` gives ideal CV/CC measurements; timers and digital I/O retain
configuration without background execution. No hardware or host files are used.

## Instrument errors

`connect()` establishes the connection, then clears stale errors. Call
`set_remote()` afterward if you want remote mode and restricted front-panel
controls; `connect()` does not send a mode-change command.
The resource is assigned before queue clearing and is closed and cleared again
if initialization fails.
Each successful write and each successfully read query response
is followed by `get_errors()`, which reads `:SYST:ERR?` until the instrument
reports no error. Nonzero entries raise `InstrumentError`. Its message contains
only the raw instrument responses, joined with newlines, without command names
or reformatted error messages. Checks consume the queue and add communication
round trips. A command may have executed even if its subsequent error check fails.

When a query raises a VISA timeout, the driver attempts error diagnostics using
the configured PyVISA timeout and query delay, without changing either setting.
Reported instrument errors raise `InstrumentError` with the original timeout
as its cause. Empty, malformed, or failed diagnostics re-raise the original
timeout. This fallback neither retries the command nor guarantees response
synchronization: a late original response can interfere with diagnostics, and
the caller may need to reconnect before continuing.

`get_errors()` returns the raw error responses as a list, or an empty list when
there are none. The virtual driver exposes its own consuming in-memory error queue.
Reading errors consumes them; there is no separate clearing operation.
Each response is retained whole, including any batched error messages. The
instrument guide documents code/message responses without specifying whether
one query consumes a single entry or the whole queue, so reads continue until
the zero-code response.

All queries use the same connection guard in `_query()`. Error-queue queries
pass `check_errors=False` to prevent recursive checks and timeout diagnostics.
Successful normal queries still check the queue: receiving a valid response
does not establish that no device or previously queued errors exist.

## Tests

Install the test dependencies and run pytest:

```sh
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
.venv/bin/python -m pytest tests/unit --cov --cov-report=term-missing
```

`tests/unit/` covers connection ownership and cleanup, framing, command strings,
response parsing, properties, channels, error handling and the virtual driver.
Shared fake VISA resources live in `tests/fakes.py`. Parameterized interface
cases replace duplicate command tests; an explicit API inventory detects public
members without test cases. Extended command cases live in `tests/extended_api.py`.

`tests/hardware/` exercises the implemented interface through real SCPI round
trips. Hardware tests are skipped unless a resource and expected model are
provided through CLI arguments:

```sh
.venv/bin/python -m pytest tests/hardware -rs \
  --visa-resource 'TCPIP0::192.0.2.1::INSTR' \
  --hardware-model DP832A --visa-backend @py --visa-timeout 5000
```

Replace the address and model with your instrument. Configuration is validated
before opening a device, and its identity must match before settings change.
Tests run serially with a fresh connection per test; do not run them concurrently
against the same instrument. Even the default hardware suite disables all
physical outputs, changes settings, consumes error/event registers, clears alarm
labels and returns the front panel to local/unlocked mode. Use an isolated bench.
Tests restore the settings they change where practical, but leave outputs off.
They check communication and response types, not calibrated electrical accuracy.

| CLI option | Purpose |
| --- | --- |
| `--visa-resource` | VISA name; enables hardware tests. |
| `--hardware-model` | Expected DP811, DP813, DP821, DP822, DP831 or DP832, optionally with an A suffix. |
| `--visa-backend` | Backend selection; omitted uses PyVISA's default. |
| `--visa-timeout` | Positive I/O timeout in milliseconds, default 5000. |
| `--visa-options` | Additional PyVISA options/attributes as JSON, e.g. `'{"baud_rate": 19200}'` for serial devices. Use dedicated arguments for the resource and timeout. |
| `--hardware-channels` | Channels to exercise, e.g. `1,2`; defaults to all physical channels. Cleanup still disables all physical outputs. |
| `--hardware-voltage` | Test voltage magnitude in `(0, 5]` V, default 1.0; negated for DP831 CH3. |
| `--hardware-current` | Test current limit in `(0, 0.1]` A, default 0.01. |
| `--hardware-allow-output` | Permit brief output activation at the configured voltage/current. |
| `--hardware-trigger` | Exercise bus triggering; requires the trigger option and `--hardware-allow-output`. |
| `--hardware-reset` | Exercise reset; discards the previous instrument configuration. |
| `--hardware-save-slot` | Overwrite a scratch slot in 1–10; its previous contents are lost. Extended cases also use this slot for timer/delay/recording files. |
| `--hardware-license` | Install a valid instrument-specific 28-character option license, a persistent change. |

Model/channel restrictions follow the [Rigol programming guide](https://www.batronix.com/pdf/Rigol/ProgrammingGuide/DP800_ProgrammingGuide_EN.pdf).
Multi-channel selection/coupling and remote sensing tests skip unsupported models
or channels. Operations needing additional flags also report explicit skips.
`--hardware-guide` enables additional guide-family round trips and requires the
relevant instrument options. It does not modify communication addresses or lock
the instrument. File/recording cases additionally require `--hardware-save-slot`;
external file tests require an existing scratch `--hardware-directory`; preset
edit/commit/apply tests require `--hardware-preset 1` (through 4). Scratch files
may be overwritten/deleted. These hardware cases have not yet been run on a real
supply. See the interface reference for the virtual model's limits.

The hardware suite includes invalid-channel write and query checks. The query
case verifies that firmware times out and the error-queue fallback raises
`InstrumentError`; hardware is required to establish that behavior. Each such
test gets its own connection to isolate potential response synchronization issues.

Dedicated lifecycle tests exercise `disconnect()` and context-manager exits.
Shutdown reads the model to disable only its physical channels; if identification
fails or the model is unknown, it attempts all three before closing. General
fixture cleanup uses the model already verified by the harness and closes its
caller-owned manager. Cleanup failures are reported as test errors.

In the development VM, networked hardware may need a host-side exception. From
the host's `dev-vm` repository, run `./manage-network-access.sh add <IPv4-address>`.

## Building distributions

```sh
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

This creates a source distribution and wheel in `dist/`. Package metadata,
dependencies, package discovery, and the build backend are defined in
`pyproject.toml`.
