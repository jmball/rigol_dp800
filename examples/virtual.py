# SPDX-License-Identifier: GPL-3.0-or-later

"""Demonstrate constant-voltage and constant-current behavior virtually."""

from virtual_dp800 import DP800


def main() -> None:
    """Run a small stateful example without hardware or external I/O."""
    with DP800(model="DP832A", load_resistance=10.0) as supply:
        supply.connect("VIRTUAL")
        channel = supply.channels[1]
        channel.voltage = 5.0
        channel.current = 1.0
        channel.output_enabled = True
        print("At a 5 V setpoint with a 1 A limit:")
        print(f"Measured voltage: {channel.measured_voltage:.3f} V")
        print(f"Measured current: {channel.measured_current:.3f} A")
        print(f"Measured power: {channel.measured_power:.3f} W")
        print(f"measure('ALL'): {channel.measure('ALL')}")

        channel.current = 0.2
        print("After lowering the current limit to 0.2 A:")
        print(f"Measured voltage: {channel.measured_voltage:.3f} V")
        print(f"Measured current: {channel.measured_current:.3f} A")
        print(f"Measured power: {channel.measured_power:.3f} W")


if __name__ == "__main__":
    main()
