# Repository guidance

## Project and layout

This is `rigol_dp800`, a Python library for controlling Rigol DP800 series power
supplies through PyVISA. The project uses a `src/` layout and setuptools.

- `src/dp800/dp800.py`: hardware driver, with methods grouped by SCPI command
  family. Commands go through `self.instr.write()` and `self.instr.query()`.
- `src/virtual_dp800/virtual_dp800.py`: hardware-free counterpart. Most setters
  are no-ops and getters return fixed placeholders; it is not a stateful simulator.
- Both packages export a lowercase `dp800` class through their `__init__.py` and
  obtain `__version__` through `importlib.metadata` for the `rigol_dp800`
  distribution, with a `0.0.0` fallback.
- `pyproject.toml`: project metadata, Python support, dependencies (`pyvisa` and
  `pyvisa-py`), package discovery, and the PEP 517 setuptools build backend.
  There is no `setup.py` or `setup.cfg`.
- `README.md`: installation and build instructions. The project is
  licensed under `GPL-3.0-or-later`; `LICENSE` contains the full GPLv3 text.
  Keep metadata and source SPDX identifiers consistent. Leave license details and
  Python compatibility requirements out of the README.

`tests/test_driver.py` contains hardware-free unittest regression tests. There is
no CI configuration or configured formatter, linter, or type checker.

## Making changes

- Preserve Python 3.10 compatibility declared in `pyproject.toml` unless the task
  explicitly changes supported versions. Do not introduce newer syntax or APIs
  without updating the compatibility contract.
- Follow the existing four-space indentation, snake_case methods, SCPI family
  grouping, and NumPy-style docstrings with parameters and return values.
- Keep public method names, signatures, optional-channel behavior, and response
  types compatible unless the requested change requires otherwise. Check actual
  implementations as well as docstrings: some disagree, such as `measure()`
  returning strings in the hardware driver.
- When changing a public API, inspect the corresponding virtual method and update
  it where appropriate. Do not assume complete parity: placeholder return types
  can differ from the hardware driver.
- Many hardware methods only warn `Not implemented.`. Treat these as unfinished
  functionality, and keep unrelated fixes out of the task.
- For SCPI changes, verify command spelling, separators, query suffixes, response
  parsing, and model restrictions against the Rigol programming guide. The driver
  module docstring links to the instrument documentation.
- Preserve the module logger and warning conventions. Avoid adding dependencies
  or replacing the packaging approach for unrelated changes.

## Setup and validation

Use an isolated environment when installation is needed:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

For a syntax check that does not import the driver or connect to hardware:

```sh
python3 -m compileall -q src
```

Run `git diff --check` for whitespace errors. For documentation-only changes,
review the text and diff; dependency installation and hardware checks are not
needed. Keep environments, bytecode, build outputs, and egg metadata untracked.

Run regression tests with `.venv/bin/python -m unittest discover -s tests -v`
after installing the checkout. For driver behavior changes, use focused tests
with a fake VISA resource that records writes and supplies query responses.
Importing the hardware package does not create a resource manager. Inject a fake
manager into connect() or patch `pyvisa.ResourceManager` before connecting.
The virtual package alone cannot validate SCPI commands or response parsing.
Report which checks ran and any hardware behavior that remains unverified.

## Hardware behavior

`connect()` opens a message-based VISA resource, configures ASCII/LF framing,
switches to remote mode, and queries identity before publishing `self.instr`.
Framing values are module-level constants shared with the virtual driver, and
conflicting settings are rejected. Reset is an explicit caller operation.
Connecting twice raises until disconnect.
Initialization failures close the resource. Managers are retained for the
connection's lifetime and released without explicitly closing them; injected
managers stay caller-owned, and default managers are obtained lazily from PyVISA.
`disconnect()` attempts to disable outputs on channels 1, 2, and 3 and return to
local mode, then closes the resource and clears `self.instr` even on failure.
Repeated disconnect calls are harmless. Account for these side effects
when designing tests. Use mocks for routine validation; exercise real hardware
only within the user's authorized task and device configuration.

## Development VM environment

This guest is provisioned by the `dev-vm` repository and uses a host-managed
network sandbox. Private and local IPv4 destinations are blocked by default.
Do not conclude that hardware is down until this policy has been considered.
If access is needed, ask the user to run this on the host from `dev-vm`:

```sh
./manage-network-access.sh add <IPv4-address>
```

For a persistent exception, the user can add the exact address to
`SANDBOX_ALLOWED_IPV4_DESTINATIONS` in `dev-vm`'s `vm-config.sh`. The guest cannot
change the host policy and must not attempt to bypass it.

Repositories beneath `/workspaces/projects` are private guest clones, not mounted
host working trees. The host cannot see uncommitted guest files, and the guest
does not have the host's upstream Git credentials. When returning work to the
host, commit the intended changes and ensure the relevant repositories are clean.
If submodules are involved, commit the deepest changed submodule first, then
commit updated gitlinks outward through the parents. Tell the user to run this
from the host's `dev-vm` repository, using their actual host project path:

```sh
./pull-project-changes.sh <host-project-path>
```

If the user says host changes were pushed into the VM or asks to integrate
`host/*` references, invoke `$integrate-host-changes`. Do not guess pending refs
or discard guest work. Project lifecycle scripts are host-side controls; do not
run them inside the guest or bypass the private-clone boundary.

Agents run as the unprivileged `agent` account, with project access, USB device
access through `dialout`, and their own rootless Docker daemon. There is no sudo
or rootful Docker socket access. Do not switch to the administrative `dev`
account or bypass this boundary. If administration is required, explain the
command and ask the user to perform it through the host-managed update workflow
or an administrative SSH session.
