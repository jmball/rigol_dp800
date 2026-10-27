# SPDX-License-Identifier: GPL-3.0-or-later

"""Read a Rigol DP800 supply, with optional explicit output enable."""

import argparse
import math
import time

import pyvisa

from dp800 import DP800


def _nonnegative_finite(value: str) -> float:
    """Parse a finite nonnegative setpoint.

    Parameters
    ----------
    value : str
        Command-line value to parse.

    Returns
    -------
    value : float
        Parsed setpoint.
    """
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be finite and nonnegative")
    return number


def main() -> None:
    """Connect to one supply channel and display its state."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "The default run does not change setpoints or enable output. "
            "On context exit, disconnect disables all physical outputs."
        ),
    )
    parser.add_argument("resource", help="VISA resource name, such as USB0::...::INSTR")
    parser.add_argument("--channel", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--backend", help="optional PyVISA backend, such as @py")
    parser.add_argument(
        "--timeout", type=_nonnegative_finite, help="VISA timeout in milliseconds"
    )
    parser.add_argument(
        "--enable-output",
        action="store_true",
        help="configure the supplied setpoints and enable this channel",
    )
    parser.add_argument("--voltage", type=_nonnegative_finite)
    parser.add_argument("--current", type=_nonnegative_finite)
    args = parser.parse_args()

    if args.enable_output and (args.voltage is None or args.current is None):
        parser.error("--enable-output requires both --voltage and --current")
    if not args.enable_output and (
        args.voltage is not None or args.current is not None
    ):
        parser.error("--voltage and --current require --enable-output")

    manager = pyvisa.ResourceManager(args.backend) if args.backend else None
    options = {"timeout": args.timeout} if args.timeout is not None else {}
    try:
        with DP800() as supply:
            supply.connect(args.resource, resource_manager=manager, **options)
            channel = supply.channels[args.channel]
            print(f"Identity: {supply.identity}")
            if args.enable_output:
                channel.output_enabled = False
                channel.voltage = args.voltage
                channel.current = args.current
                channel.output_enabled = True
                time.sleep(0.5)
            print(f"Channel {args.channel} output enabled: {channel.output_enabled}")
            print(f"Voltage setpoint: {channel.voltage:.3f} V")
            print(f"Current setpoint: {channel.current:.3f} A")
            print(f"Measured voltage: {channel.measured_voltage:.3f} V")
            print(f"Measured current: {channel.measured_current:.3f} A")
            print(f"Measured power: {channel.measured_power:.3f} W")
    finally:
        if manager is not None:
            manager.close()


if __name__ == "__main__":
    main()
