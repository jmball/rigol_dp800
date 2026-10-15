# Driver interface

The hardware and virtual drivers expose the same `DP800` interface. This reference
covers the command families in the December 2015 Rigol DP800 programming guide
(PGH03108-1110), available from the [programming guide mirror](https://www.batronix.com/pdf/Rigol/ProgrammingGuide/DP800_ProgrammingGuide_EN.pdf).
Model/option restrictions are enforced by the real instrument. A Python member
being present does not mean every model supports that operation. Later firmware
commands outside that guide are not part of this inventory.

Channel arguments identify physical outputs without changing `selected_channel`.
The guide's selected-channel commands (delay, timer, monitor and preset editing)
operate on `selected_channel`; select it explicitly before calling those APIs.
Those operations are deliberately not exposed on `DP800Channel`, since doing so
would silently change the parent's channel selection. Channel views additionally
expose increment sizes, triggered levels, tracking and questionable registers.

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
supply.delay_time_method = ("INC", 1, 2)   # Method, base/on time, step/off time.
supply.monitor_voltage_condition = (">V", "AND")
supply.timer_cycles = ("N", 3)             # ("I", None) selects infinite cycles.
supply.timer_template_object = ("V", 0.1)  # Vary voltage, hold current at 0.1 A.
supply.timer_template = "SINE"
```

Arguments remain explicit where needed:

```python
supply.set_delay_parameters(0, True, 2)    # Entry index, output state, seconds.
supply.set_timer_parameters(0, 1.0, 0.01, 2.0)
entries = supply.get_timer_parameters(first=0, count=3)
supply.set_trigger_input_source(["CH1", "CH2"], line=0)
supply.set_preset_voltage(1, 2.0)
supply.save_preset(1)                      # Commit edited preset values.
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
or an external path with the matching suffix. `save_setup()` and `recall_setup()`
retain their existing state-only slot API. `save_named_setup()` additionally
specifies the internal state filename. Internal deletion, locking and validity
queries also support ROF recording files. External file/directory operations
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
| Output and source protection enable/threshold commands | Existing OCP/OVP APIs |
| Output range and source voltage range | `output_range` |
| Output timer and `:TIMEr` entry/state commands | `set/get_timer_parameters()`, `timer_enabled` |
| Local state save/recall commands and `*SAV`/`*RCL` | Existing setup methods; named save where needed |
| External store/recall and `:MMEMory` load/store | `save_file()`, `recall_file()` |
| `:SYST:BRIGhtness`, `:SYST:RGBBrightness` | `brightness` |
| `:SYST:KLOC:STAT`, `:SYST:RWLock` | `keylock_enabled` |
| `:TRIG:IN:CHTYpe`, `:TRIG:SOURce` | `trigger_source` |
| `:TRIG:IN:IMMediate`, `:INITiate` | `init_trigger()` |
| Trigger input voltage/current and source triggered levels | `set/get_source_trigger()` / channel triggered properties |

## Changes from the unfinished API

The old warning-only names have been replaced or completed as follows. Existing
implemented channel/getter/setter APIs remain available.

| Old unfinished names | Implemented interface |
| --- | --- |
| `set/get_delay_parameters` | Indexed methods with index/state/duration arguments |
| `set/get_delay_state` | `delay_enabled` |
| `set/get_delay_state_pattern` | `delay_state_pattern` |
| `set/get_delay_stop_condition` | `delay_stop_condition` |
| `set/get_delay_time_method` | `delay_time_method` |
| `set_output_range`, `set_voltage_range` | `output_range` |
| `set/get_output_timer` | `set/get_timer_parameters` |
| `set/get_output_timer_enable` | `timer_enabled` |
| `set/get_output_track` | Completed channel-aware methods |
| `set/get_current_step`, `set/get_voltage_step` | Completed channel-aware methods |
| `set/get_source_trigger` | Completed; getter no longer takes a level |
| `clear_ocp_circuit`, `clear_ovp_circuit` | Completed, with optional channel argument |
| `set/get_beeper` | `beeper_enabled`; `beep()` sounds once |
| `set/get_gpib_config` | `gpib_address` |
| `set/get_lan_config` | Individual `lan_*` properties and `apply_lan_config()` |
| `set/get_rs232_config` | Individual `rs232_*` properties |
| `set/get_contrast`, `set/get_brightness` | `contrast`, `brightness` |
| `set/get_key_keylock` | `set/get_key_lock(key, ...)` |
| `set/get_language`, `set/get_lock` | `language`, `locked` |
| `set/get_on_off_sync`, `set/get_otp_enable` | `on_off_sync_enabled`, `otp_enabled` |
| `set/get_power_on_config_mode` | `power_on_config_mode` |
| `set_screen_saver_enable`, `set/get_track_mode`, `get_scpi_version` | `screen_saver_enabled`, `track_mode`, `scpi_version` |

`set_apply()` rejects current-only and empty configurations before sending a
command. Channel-only selection is supported. `get_apply()` raises `ValueError`
if a function is supplied without a channel, rather than sending a known invalid
query. Its complete response is a tuple. The virtual driver's return types now
match the hardware driver, including identity, options and measurements.

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

## Complete public inventory

The signatures in the source provide argument types and defaults. The following
tables list every public instrument member, grouped by command family.

### Connection lifecycle

| Member | Access | Result |
| --- | --- | --- |
| `connect(resource_name, resource_manager)` | method | `None` |
| `disconnect()` | method | `None` |

### Channel views

| Member | Access | Result |
| --- | --- | --- |
| `channels` | read-only | `Mapping[int, DP800Channel]` |

### ANALyzer

| Member | Access | Result |
| --- | --- | --- |
| `analyzer_current_time` | read/write | `int` |
| `analyzer_start_time` | read/write | `int` |
| `analyzer_end_time` | read/write | `int` |
| `analyzer_object` | read/write | `str` |
| `analyzer_file` | read-only | `str` |
| `analyzer_results` | read-only | `dict[str, float]` |
| `analyze()` | method | `None` |
| `open_recording(location)` | method | `None` |
| `get_recorded_values(time)` | method | `tuple[float, float, float]` |

### APPLy

| Member | Access | Result |
| --- | --- | --- |
| `set_apply(channel, voltage, current)` | method | `None` |
| `get_apply(channel, function)` | method | `float \| tuple[str, str, float, float]` |

### DELAY

| Member | Access | Result |
| --- | --- | --- |
| `set_delay_cycles(finite, cycles)` | method | `None` |
| `get_delay_cycles()` | method | `str \| tuple[str, int]` |
| `delay_end_state` | read/write | `str` |
| `delay_groups` | read/write | `int` |
| `delay_enabled` | read/write | `bool` |
| `delay_state_pattern` | read/write | `str` |
| `set_delay_parameters(index, enabled, duration)` | method | `None` |
| `get_delay_parameters(first, count)` | method | `list[tuple[int, bool, int]]` |
| `delay_stop_condition` | read/write | `tuple[str, float \| None]` |
| `delay_time_method` | read/write | `tuple[str, int, int]` |

### DISPlay

| Member | Access | Result |
| --- | --- | --- |
| `display_mode` | read/write | `str` |
| `display_enabled` | read/write | `bool` |
| `display_text` | read-only | `str` |
| `set_display_text(text, x, y)` | method | `None` |
| `clear_display_text()` | method | `None` |

### IEEE488.2

| Member | Access | Result |
| --- | --- | --- |
| `clear_event_registers()` | method | `None` |
| `standard_event_enable_register` | read/write | `int` |
| `get_standard_event_register()` | method | `int` |
| `identity` | read-only | `list[str]` |
| `set_opc()` | method | `None` |
| `get_opc()` | method | `int` |
| `option_installation_status` | read-only | `str` |
| `power_on_status_clear_bit` | read/write | `int` |
| `recall_setup(number)` | method | `None` |
| `reset()` | method | `None` |
| `save_setup(number)` | method | `None` |
| `status_byte_enable_register` | read/write | `int` |
| `status_byte_register` | read-only | `int` |
| `trigger()` | method | `None` |
| `self_test_results` | read-only | `list[str]` |
| `wait()` | method | `None` |

### INITiate

| Member | Access | Result |
| --- | --- | --- |
| `init_trigger()` | method | `None` |

### INSTrument

| Member | Access | Result |
| --- | --- | --- |
| `trigger_coupling_channels` | read/write | `str \| list[str]` |
| `selected_channel` | read/write | `int` |

### LIC

| Member | Access | Result |
| --- | --- | --- |
| `install_options(options_licence)` | method | `None` |

### MEASure

| Member | Access | Result |
| --- | --- | --- |
| `measure(func, channel)` | method | `str \| list[str]` |

### MEMory

| Member | Access | Result |
| --- | --- | --- |
| `save_file(file_type, location)` | method | `None` |
| `recall_file(file_type, location)` | method | `None` |
| `delete_memory_file(file_type, slot)` | method | `None` |
| `set_memory_lock(file_type, slot, enabled)` | method | `None` |
| `get_memory_lock(file_type, slot)` | method | `bool` |
| `memory_file_exists(file_type, slot)` | method | `bool` |

### MMEMory

| Member | Access | Result |
| --- | --- | --- |
| `directory` | read/write | `str` |
| `directory_entries` | read-only | `list[str]` |
| `available_disks` | read-only | `list[str]` |
| `make_directory(path)` | method | `None` |
| `delete_file(path)` | method | `None` |

### MONItor

| Member | Access | Result |
| --- | --- | --- |
| `monitor_voltage` | read/write | `float` |
| `monitor_voltage_condition` | read/write | `tuple[str, str]` |
| `monitor_current` | read/write | `float` |
| `monitor_current_condition` | read/write | `tuple[str, str]` |
| `monitor_power` | read/write | `float` |
| `monitor_power_condition` | read/write | `str` |
| `monitor_enabled` | read/write | `bool` |
| `monitor_stop_actions` | read-only | `tuple[bool, bool, bool]` |
| `set_monitor_stop_action(action, enabled)` | method | `None` |

### OUTPut

| Member | Access | Result |
| --- | --- | --- |
| `get_output_mode(channel)` | method | `str` |
| `get_ocp(channel)` | method | `bool` |
| `clear_ocp_label(channel)` | method | `None` |
| `set_ocp_enable(enable, channel)` | method | `None` |
| `get_ocp_enable(channel)` | method | `bool` |
| `set_ocp_value(value, channel)` | method | `None` |
| `get_ocp_value(channel, limit)` | method | `float` |
| `get_ovp(channel)` | method | `bool` |
| `clear_ovp_label(channel)` | method | `None` |
| `set_ovp_enable(enable, channel)` | method | `None` |
| `get_ovp_enable(channel)` | method | `bool` |
| `set_ovp_value(value, channel)` | method | `None` |
| `get_ovp_value(channel, limit)` | method | `float` |
| `set_output_sense_enable(enable, channel)` | method | `None` |
| `get_output_sense_enable(channel)` | method | `bool` |
| `set_output_enable(enable, channel)` | method | `None` |
| `get_output_enable(channel)` | method | `bool` |
| `output_range` | read/write | `str` |
| `set_output_track(enabled, channel)` | method | `None` |
| `get_output_track(channel)` | method | `bool` |

### PRESet

| Member | Access | Result |
| --- | --- | --- |
| `preset_key` | read/write | `str` |
| `apply_preset()` | method | `None` |
| `reset_preset(preset)` | method | `None` |
| `save_preset(preset)` | method | `None` |
| `set_preset_voltage(preset, value)` | method | `None` |
| `get_preset_voltage(preset, limit)` | method | `float` |
| `set_preset_current(preset, value)` | method | `None` |
| `get_preset_current(preset, limit)` | method | `float` |
| `set_preset_otp_enabled(preset, value)` | method | `None` |
| `get_preset_otp_enabled(preset)` | method | `bool` |
| `set_preset_tracking_enabled(preset, value)` | method | `None` |
| `get_preset_tracking_enabled(preset)` | method | `bool` |
| `set_preset_ocp(preset, enabled, value)` | method | `None` |
| `get_preset_ocp(preset, limit)` | method | `tuple[bool, float]` |
| `set_preset_ovp(preset, enabled, value)` | method | `None` |
| `get_preset_ovp(preset, limit)` | method | `tuple[bool, float]` |

### RECorder

| Member | Access | Result |
| --- | --- | --- |
| `recorder_enabled` | read/write | `bool` |
| `recorder_period` | read/write | `int` |
| `recorder_destination` | read-only | `str` |
| `set_recorder_destination(location, filename)` | method | `None` |

### SOURce

| Member | Access | Result |
| --- | --- | --- |
| `set_current(current, channel)` | method | `None` |
| `get_current(channel)` | method | `float` |
| `set_voltage(voltage, channel)` | method | `None` |
| `get_voltage(channel)` | method | `float` |
| `set_current_step(value, channel)` | method | `None` |
| `get_current_step(channel, default)` | method | `float` |
| `set_voltage_step(value, channel)` | method | `None` |
| `get_voltage_step(channel, default)` | method | `float` |
| `clear_ocp_circuit(channel)` | method | `None` |
| `clear_ovp_circuit(channel)` | method | `None` |
| `set_source_trigger(func, level, channel)` | method | `None` |
| `get_source_trigger(func, channel, limit)` | method | `float` |

### STATus

| Member | Access | Result |
| --- | --- | --- |
| `questionable_condition` | read-only | `int` |
| `questionable_enable_register` | read/write | `int` |
| `instrument_questionable_enable_register` | read/write | `int` |
| `get_questionable_event()` | method | `int` |
| `get_instrument_questionable_event()` | method | `int` |
| `get_channel_questionable_condition(channel)` | method | `int` |
| `get_channel_questionable_enable(channel)` | method | `int` |
| `get_channel_questionable_event(channel)` | method | `int` |
| `set_channel_questionable_enable(value, channel)` | method | `None` |

### STORe

| Member | Access | Result |
| --- | --- | --- |
| `save_named_setup(slot, filename)` | method | `None` |

### SYSTem

| Member | Access | Result |
| --- | --- | --- |
| `beeper_enabled` | read/write | `bool` |
| `brightness` | read/write | `int` |
| `contrast` | read/write | `int` |
| `gpib_address` | read/write | `int` |
| `lan_autoip_enabled` | read/write | `bool` |
| `lan_dhcp_enabled` | read/write | `bool` |
| `lan_dns` | read/write | `str` |
| `lan_gateway` | read/write | `str` |
| `lan_ip_address` | read/write | `str` |
| `lan_mac_address` | read-only | `str` |
| `lan_manualip_enabled` | read/write | `bool` |
| `lan_subnet_mask` | read/write | `str` |
| `rs232_baud_rate` | read/write | `int` |
| `rs232_data_bits` | read/write | `int` |
| `rs232_flow_control_enabled` | read/write | `bool` |
| `rs232_parity` | read/write | `str` |
| `rs232_stop_bits` | read/write | `int` |
| `language` | read/write | `str` |
| `locked` | read/write | `bool` |
| `on_off_sync_enabled` | read/write | `bool` |
| `otp_enabled` | read/write | `bool` |
| `power_on_config_mode` | read/write | `str` |
| `screen_saver_enabled` | read/write | `bool` |
| `track_mode` | read/write | `str` |
| `scpi_version` | read-only | `str` |
| `get_errors()` | method | `list[str]` |
| `keylock_enabled` | read/write | `bool` |
| `set_local()` | method | `None` |
| `set_remote()` | method | `None` |
| `temperature_test_result` | read-only | `float` |
| `beep()` | method | `None` |
| `apply_lan_config()` | method | `None` |
| `set_key_lock(key, enabled)` | method | `None` |
| `get_key_lock(key)` | method | `bool` |
| `get_board_test_results(board)` | method | `list[str]` |
| `fan_test_result` | read-only | `str` |

### TIMEr

| Member | Access | Result |
| --- | --- | --- |
| `timer_cycles` | read/write | `tuple[str, int \| None]` |
| `timer_end_state` | read/write | `str` |
| `timer_groups` | read/write | `int` |
| `timer_enabled` | read/write | `bool` |
| `timer_template` | read/write | `str` |
| `timer_template_object` | read/write | `tuple[str, float]` |
| `timer_template_max` | read/write | `float` |
| `timer_template_min` | read/write | `float` |
| `timer_template_inverted` | read/write | `bool` |
| `timer_template_fall_rate` | read/write | `int` |
| `timer_template_rise_rate` | read/write | `int` |
| `timer_template_interval` | read/write | `int` |
| `timer_template_period` | read/write | `int` |
| `timer_template_points` | read/write | `int` |
| `timer_template_symmetry` | read/write | `int` |
| `timer_template_width` | read/write | `int` |
| `construct_timer_template()` | method | `None` |
| `set_timer_parameters(index, voltage, current, duration)` | method | `None` |
| `get_timer_parameters(first, count)` | method | `list[tuple[int, float, float, float]]` |

### TRIGger

| Member | Access | Result |
| --- | --- | --- |
| `trigger_source` | read/write | `str` |
| `trigger_delay` | read/write | `float` |
| `set_trigger_input_enabled(value, line)` | method | `None` |
| `get_trigger_input_enabled(line)` | method | `bool` |
| `set_trigger_input_source(value, line)` | method | `None` |
| `get_trigger_input_source(line)` | method | `list[str]` |
| `set_trigger_input_response(value, line)` | method | `None` |
| `get_trigger_input_response(line)` | method | `str` |
| `set_trigger_input_sensitivity(value, line)` | method | `None` |
| `get_trigger_input_sensitivity(line)` | method | `str` |
| `set_trigger_input_type(value, line)` | method | `None` |
| `get_trigger_input_type(line)` | method | `str` |
| `set_trigger_output_enabled(value, line)` | method | `None` |
| `get_trigger_output_enabled(line)` | method | `bool` |
| `set_trigger_output_source(value, line)` | method | `None` |
| `get_trigger_output_source(line)` | method | `str` |
| `set_trigger_output_duty_cycle(value, line)` | method | `None` |
| `get_trigger_output_duty_cycle(line)` | method | `int` |
| `set_trigger_output_period(value, line)` | method | `None` |
| `get_trigger_output_period(line)` | method | `float` |
| `set_trigger_output_polarity(value, line)` | method | `None` |
| `get_trigger_output_polarity(line)` | method | `str` |
| `set_trigger_output_signal(value, line)` | method | `None` |
| `get_trigger_output_signal(line)` | method | `str` |
| `set_trigger_output_condition(condition, value, line)` | method | `None` |
| `get_trigger_output_condition(line, limit)` | method | `tuple[str, float \| None]` |

### Limits

| Member | Access | Result |
| --- | --- | --- |
| `get_limit(setting, limit)` | method | `float` |
