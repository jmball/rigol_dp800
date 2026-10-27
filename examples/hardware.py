# SPDX-License-Identifier: GPL-3.0-or-later

"""Briefly power channel 1 at 5 V with a 0.1 A current limit, then measure it."""

import argparse
import time

from dp800 import DP800


def parse_args() -> argparse.Namespace:
    """Read the instrument address from the command line.

    Returns
    -------
    argparse.Namespace
        Arguments containing the VISA resource name.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource", help="VISA resource name, such as USB0::...::INSTR")
    return parser.parse_args()


def main() -> None:
    """Configure channel 1, enable its output, and read measurements."""
    args = parse_args()
    with DP800() as supply:
        supply.connect(args.resource)
        print(f"Identity: {supply.identity}")

        channel = supply.channels[1]
        channel.output_enabled = False
        channel.voltage = 5.0
        channel.current = 0.1
        channel.output_enabled = True
        time.sleep(0.5)  # Allow the output to settle before measuring.

        print(f"Measured voltage: {channel.measured_voltage:.3f} V")
        print(f"Measured current: {channel.measured_current:.3f} A")
        print(f"Measured power: {channel.measured_power:.3f} W")
        channel.output_enabled = False
    # Leaving the context disconnects and disables all physical outputs.


if __name__ == "__main__":
    main()
