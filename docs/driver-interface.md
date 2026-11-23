# Driver interface

The hardware and virtual drivers expose the same `DP800` interface. This reference
covers the command families in the June 2021 Rigol DP800 programming guide
(PGH03109-1110), available from the [programming guide mirror](https://www.batronix.com/files/Rigol/Labornetzteile/DP800/DP800_ProgrammingGuide_EN-22.pdf).
Model/option restrictions are enforced by the real instrument. A Python member
being present does not mean every model supports that operation. Later firmware
commands outside that guide are not covered here.

Channel arguments identify physical outputs without changing `selected_channel`.
The guide's selected-channel commands (delay, timer, monitor and preset editing)
operate on `selected_channel`; select it explicitly before calling those APIs.
Those operations are deliberately not exposed on `DP800Channel`, since doing so
would silently change the parent's channel selection. Channel views additionally
expose increment sizes, triggered levels, tracking and questionable registers.

`supply.available_channels` queries identity and returns the physical channel
numbers for the connected model as a tuple. It supports DP811, DP813, DP821,
DP822, DP831 and DP832, including their A variants. Malformed identity responses
and unsupported models raise `ValueError`; discovery requires a connection.
The `channels` mapping continues to provide stable views numbered 1–3, with
`available_channels` identifying which views represent physical outputs.

Each channel's `voltage_limits` and `current_limits` properties return numerical
`(minimum, maximum)` tuples in volts and amperes. They check availability through
identity, then query `:SOUR<n>:VOLT? MIN/MAX` or `:SOUR<n>:CURR? MIN/MAX` without
changing channel selection. Bounds are settable values, which can exceed nominal
ratings. Single-channel models report their currently selected output range;
negative outputs have numerically ordered voltage bounds, such as `(-32.0, 0.0)`.
These properties are read-only and uncached, so reconnects and range changes are
reflected on the next access. An unavailable channel raises `ValueError` before
its source is queried. Other channel operations leave availability enforcement
to the instrument.

Shutdown reads identity to disable physical outputs on known models, without
caching a channel count. Unknown models or failed discovery fall back to all
three outputs; cleanup still closes the resource after errors.

Use a full VISA resource name. ASRL serial names use the guide's CRLF end marker;
other transports use LF. Conflicting framing options warn and are ignored.

All operations require a connection except access to the channel mapping and
channel numbers. Setters perform I/O immediately. Reads that consume a register
or queue remain methods rather than properties. File paths and display text are
ASCII strings; quotes are escaped and line terminators are rejected. Timer and
delay reads decode and validate the guide's ASCII block headers.

## Properties and indexed methods

Scalar settings are properties: for example, `supply.beeper_enabled = False`,
`supply.delay_enabled = True`, `supply.trigger_source = "BUS"`, and
`supply.rs232_baud_rate = 19200`. Multi-field settings use tuples:

```python
supply.delay_stop_condition = (">V", 5.0)  # ("NONE", None) disables the condition.
supply.delay_time_method = ("INC", 1, 2)  # Method, base/on time, step/off time.
supply.monitor_voltage_condition = (">V", "AND")
supply.timer_cycles = ("N", 3)  # ("I", None) selects infinite cycles.
supply.timer_template_object = ("V", 0.1)  # Vary voltage, hold current at 0.1 A.
supply.timer_template = "SINE"
```

Arguments remain explicit where needed:

```python
supply.set_delay_parameters(0, True, 2)  # Entry index, output state, seconds.
supply.set_timer_parameters(0, 1.0, 0.01, 2.0)
entries = supply.get_timer_parameters(first=0, count=3)
supply.set_trigger_input_source(["CH1", "CH2"], line=0)
supply.set_preset_voltage(1, 2.0)
supply.save_preset(1)  # Commit edited preset values.
supply.preset_key = "USER1"
supply.apply_preset()
```

Delay entry reads return `(index, enabled, seconds)` tuples. Timer entry reads
return `(index, volts, amps, seconds)` tuples. Indexes start at zero and range
from 0 to 2047. Internal file slots range from 1 to 10; user presets from 1 to 4;
digital lines from 0 to 3. Omitted digital-line arguments use the instrument's
selected line. Digital input source reads return lists of channel names.

The `monitor_stop_actions` tuple contains output-off, warning and beeper enable
states, in that order. Change one action with `set_monitor_stop_action()`.
Analyzer results are a dictionary preserving the instrument's statistic labels;
values are floats with unit suffixes removed. `get_recorded_values()` returns
voltage, current and power as three floats. Memory validity and lock queries
return booleans. File listings are lists of strings.

## Bounds, files and protection

`get_ocp_value()`, `get_ovp_value()`, `get_source_trigger()` and the numeric preset
getters accept `limit="MIN"` or `limit="MAX"`. Step getters accept `default=True`.
Scalar properties with bound-query support use `get_limit(property_name, limit)`:

- `analyzer_start_time`, `analyzer_end_time`, `delay_stop_condition`;
- `monitor_current`, `monitor_voltage`, `monitor_power`;
- `brightness`, `contrast`;
- `timer_template_min`, `timer_template_max`, `timer_template_object`;
- `trigger_delay`.

`save_file(file_type, location)` and `recall_file(file_type, location)` accept RSF
(state), RTF (timer) or RDF (delay). A location is either an internal integer slot
or an external path with the matching suffix. `save_setup(number)` stores the
current instrument state in an internal slot, and `recall_setup(number)` restores
state from that slot. `save_named_setup()` also specifies the internal state
filename. Internal deletion, locking and validity queries also support ROF
recording files. External file/directory operations
never act on the controlling computer's filesystem.

`set_recorder_destination(slot, filename)` chooses an internal recording location;
`set_recorder_destination(path)` chooses an external location. Stop the recorder
before changing its period or destination. Open the resulting ROF file with
`open_recording()` before configuring or running the analyzer.

`clear_ocp_label()` and `clear_ovp_label()` only clear alarm labels.
**`clear_ocp_circuit()` and `clear_ovp_circuit()` also re-enable the output.** They
are separate operations, not aliases. Remove the fault before using a circuit
clear. Single-channel `output_range` accepts `LOW`/`HIGH`; its getter returns
the rated voltage/current string. Triggering and starting timers/delayers can
change output settings/state. LAN changes are staged until `apply_lan_config()`,
which may interrupt the connection. File writes, preset commits and option
installation can persist on the instrument.

## Consolidated command equivalents

These guide variants share one public implementation:

| Guide variants | Public API |
| --- | --- |
| `:OUTP:CVCC?`, `:OUTP:MODE?` | `get_output_mode()` / channel `output_mode` |
| Protection `:ALAR?`, `:QUES?`, source `:PROT:TRIP?` | `get_ocp()`, `get_ovp()` / channel alarm properties |
| Output and source protection enable/threshold commands | `get_ocp_enable()`, `get_ocp_value()`, `get_ovp_enable()`, `get_ovp_value()` and matching setters |
| Output range and source voltage range | `output_range` |
| Output timer and `:TIMEr` entry/state commands | `set/get_timer_parameters()`, `timer_enabled` |
| Local state save/recall commands and `*SAV`/`*RCL` | `save_setup()`, `recall_setup()`, `save_named_setup()` |
| External store/recall and `:MMEMory` load/store | `save_file()`, `recall_file()` |
| `:SYST:BRIGhtness`, `:SYST:RGBBrightness` | `brightness` |
| `:SYST:KLOC:STAT`, `:SYST:RWLock` | `keylock_enabled` |
| `:TRIG:IN:CHTYpe`, `:TRIG:SOURce` | `trigger_source` |
| `:TRIG:IN:IMMediate`, `:INITiate` | `init_trigger()` |
| Trigger input voltage/current and source triggered levels | `set/get_source_trigger()` / channel triggered properties |

## Apply commands and response types

`set_apply()` accepts a channel selection, voltage, and current. Current requires
a voltage, and at least a channel or voltage must be supplied. `get_apply()`
returns a scalar for a channel/function query, `(channel, rating, voltage, current)`
when only a channel is specified, and `(voltage, current)` when called without
arguments. Specifying a function requires a channel. The channel and rating are
split from the instrument's combined field, such as `CH1:30V/3A`.
The virtual driver uses the same public interface and response types as the
hardware driver, including identity, options, and measurements.

## Virtual behavior

```python
from virtual_dp800 import DP800

with DP800(model="DP832A", load_resistance=10.0) as supply:
    supply.connect("virtual")
    supply.channels[1].voltage = 5.0
    supply.channels[1].current = 1.0
    supply.channels[1].output_enabled = True
    assert supply.channels[1].measured_current == 0.5
```

The virtual supply creates no VISA manager, network connection, thread or host
file. It uses the hardware API and response parsers with an in-memory transport.
Physical channel availability and nominal ranges follow the configured model;
the public channel mapping still contains stable views numbered 1–3. Unsupported
channels report instrument errors. State and files survive reconnects; disconnect
leaves outputs and active functions off. Reset restores operating settings while
preserving saved files. Two virtual instances never share state.

Measurements are ideal DC values. With no load resistance, current is zero. A
positive resistance produces ideal CV/CC operation; threshold trips switch an
output off. Monitor output-off responses, protection labels/circuit clearing,
triggered levels, presets, files and status/event reads support application tests.
Error checking defaults to enabled and errors use the same `InstrumentError`.

There is no real-time execution. Timer/delay entries and digital I/O settings are
stored; waveform construction generates deterministic approximate template
entries, not a firmware-accurate waveform. Starting/stopping a recording captures
two samples of the selected channel instead of continuous acquisition. Analyzer
statistics use those samples. Trigger delay and serial/LAN configuration values
are retained without sleeping or contacting other systems. The virtual interface
is suitable for control-flow tests, not timing or electrical certification.
