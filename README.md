# rigol_dp800

Python library for controlling Rigol DP800 series power supplies through PyVISA.
Requires Python 3.10 or newer.

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

## Building distributions

```sh
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

This creates a source distribution and wheel in `dist/`. Package metadata,
dependencies, package discovery, and the build backend are defined in
`pyproject.toml`.

## License

You may redistribute and modify rigol_dp800 under the GNU General Public License,
version 3 or, at your option, any later version (`GPL-3.0-or-later`). See
[LICENSE](LICENSE) for the full terms, including the warranty disclaimer.
