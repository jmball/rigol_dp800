# SPDX-License-Identifier: GPL-3.0-or-later

"""The virtual driver exposes the hardware driver's public interface.

Members are compared through static class lookup, so the check does not rely on
the virtual driver inheriting from the hardware driver. Behavior is covered by
the virtual state tests; this check catches interface drift.
"""

import inspect

import pytest

import dp800
import virtual_dp800

HARDWARE, VIRTUAL = dp800.DP800, virtual_dp800.DP800

# Virtual-only construction options; everything else must match exactly.
VIRTUAL_CONSTRUCTOR_OPTIONS = {
    "check_errors",
    "model",
    "serial_number",
    "load_resistance",
}


def public_members(cls):
    names = {
        name
        for name in dir(cls)
        if not name.startswith("_") or name in ("__enter__", "__exit__")
    }
    return {name: inspect.getattr_static(cls, name) for name in names}


def kind(member):
    if isinstance(member, property):
        return "read/write property" if member.fset else "read-only property"
    if isinstance(member, staticmethod):
        return "staticmethod"
    if isinstance(member, classmethod):
        return "classmethod"
    return "method" if callable(member) else "attribute"


def function(member):
    if isinstance(member, property):
        return member.fget
    return (
        member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
    )


HARDWARE_MEMBERS = public_members(HARDWARE)
VIRTUAL_MEMBERS = public_members(VIRTUAL)


def test_public_member_names_match():
    assert sorted(VIRTUAL_MEMBERS) == sorted(HARDWARE_MEMBERS)


def interface_differences(hardware_members, virtual_members):
    """Describe kind and signature mismatches for members present in both."""
    differences = []
    for name in sorted(hardware_members.keys() & virtual_members.keys()):
        hardware, virtual = hardware_members[name], virtual_members[name]
        if kind(virtual) != kind(hardware):
            differences.append(f"{name}: {kind(virtual)} != {kind(hardware)}")
            continue
        accessors = [(function(hardware), function(virtual))]
        if isinstance(hardware, property) and hardware.fset is not None:
            accessors.append((hardware.fset, virtual.fset))
        for expected, actual in accessors:
            if not callable(expected):
                continue
            expected = inspect.signature(expected, eval_str=True)
            actual = inspect.signature(actual, eval_str=True)
            if actual != expected:
                differences.append(f"{name}: {actual} != {expected}")
    return differences


def test_member_kinds_and_signatures_match():
    assert interface_differences(HARDWARE_MEMBERS, VIRTUAL_MEMBERS) == []


def test_differences_are_detected():
    class Drifted(VIRTUAL):
        def set_voltage(self, voltage, channel=1):  # Changed default.
            pass

        @property
        # Deliberately invalid override: the parity check must detect it.
        def brightness(self) -> int:  # ty: ignore[incompatible-property-override]
            return 0

    differences = interface_differences(HARDWARE_MEMBERS, public_members(Drifted))
    assert [item.partition(":")[0] for item in differences] == [
        "brightness",
        "set_voltage",
    ]


def test_constructor_only_adds_virtual_options():
    hardware = inspect.signature(HARDWARE.__init__, eval_str=True).parameters
    virtual = inspect.signature(VIRTUAL.__init__, eval_str=True).parameters
    for name, parameter in hardware.items():
        assert virtual[name] == parameter
    extra = virtual.keys() - hardware.keys()
    assert extra == VIRTUAL_CONSTRUCTOR_OPTIONS
    # Every virtual-only option has a default, so DP800() works for both drivers.
    assert all(virtual[name].default is not inspect.Parameter.empty for name in extra)


@pytest.mark.parametrize("name", ["DP800Channel", "InstrumentError"])
def test_packages_share_channel_and_error_types(name):
    assert getattr(virtual_dp800, name) is getattr(dp800, name)


def test_virtual_channels_are_shared_channel_views():
    supply = VIRTUAL()
    assert all(
        type(channel) is dp800.DP800Channel for channel in supply.channels.values()
    )
