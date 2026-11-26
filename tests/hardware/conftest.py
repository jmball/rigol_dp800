# SPDX-License-Identifier: GPL-3.0-or-later

"""A fresh connection per hardware test; no device is opened during collection."""

import pytest
import pyvisa

from dp800 import DP800


@pytest.fixture
def bench_config(pytestconfig):
    config = pytestconfig._dp800_hardware
    if config is None:
        pytest.skip("provide --visa-resource and --hardware-model")
    return config


@pytest.fixture
def visa_manager(bench_config):
    manager = (
        pyvisa.ResourceManager(bench_config.backend)
        if bench_config.backend
        else pyvisa.ResourceManager()
    )
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture(autouse=True)
def model_and_option_support(request, pytestconfig):
    """Skip cases outside the guide's model/channel or installed-option support.

    supported_on markers are checked from configuration without I/O. A channel
    parameter (channel_number) narrows the check to that channel. requires_option
    markers read *OPT? through the test's connected hardware fixture.
    """
    config = pytestconfig._dp800_hardware
    if config is None:
        return
    callspec = getattr(request.node, "callspec", None)
    channel = callspec.params.get("channel_number") if callspec else None
    if channel is not None and channel not in config.channels:
        return  # The channel fixture reports absent or excluded channels.
    for marker in request.node.iter_markers("supported_on"):
        (feature,) = marker.args
        if not config.supports(feature, channel):
            where = f"{config.model} CH{channel}" if channel else config.model
            pytest.skip(f"{feature} is not supported on {where}")
    options = [
        marker.args[0] for marker in request.node.iter_markers("requires_option")
    ]
    if options:
        supply = request.getfixturevalue("hardware")
        installed = {
            item.strip() for item in supply.option_installation_status.split(",")
        }
        missing = [option for option in options if option not in installed]
        if missing:
            pytest.skip("requires the " + ", ".join(missing) + " option")


# Applied in order to every physical channel after each test.
SAFE_CHANNEL_STATE = (("output_enabled", False), ("voltage", 0), ("current", 0))


def connect_verified(supply, config, manager):
    """Connect and check the bench model before any setting changes."""
    supply.connect(
        config.resource_name,
        resource_manager=manager,
        timeout=config.timeout,
        **config.resource_options,
    )
    identity_fields = supply.identity.split(",")
    assert len(identity_fields) == 4
    assert identity_fields[1].strip().upper() == config.model, (
        "Connected model differs from --hardware-model"
    )


@pytest.fixture
def hardware(bench_config, visa_manager):
    manager = visa_manager
    supply = DP800()
    verified = False
    try:
        connect_verified(supply, bench_config, manager)
        verified = True
        for number in bench_config.physical_channels:
            supply.channels[number].output_enabled = False
        yield supply
    finally:
        failures = []
        if verified and not supply.connected:
            # Lifecycle tests and invalidated sessions end disconnected; reconnect
            # so the safe output state below is still applied.
            try:
                connect_verified(supply, bench_config, manager)
            except Exception as error:
                failures.append(error)
                verified = False  # Never change settings on an unverified session.
        if verified and supply.connected:
            # Disable every physical output, then return its setpoints to 0 V/0 A,
            # continuing after reported command errors.
            for number in bench_config.physical_channels:
                for name, value in SAFE_CHANNEL_STATE:
                    if not supply.connected:
                        break
                    try:
                        setattr(supply.channels[number], name, value)
                    except Exception as error:
                        failures.append(error)
            for operation in (
                lambda: setattr(supply, "keylock_enabled", False),
                supply.set_local,
            ):
                if not supply.connected:
                    break
                try:
                    operation()
                except Exception as error:
                    failures.append(error)
        # Harness cleanup uses the already verified bench model, avoiding another
        # identity query during failure teardown. Lifecycle has separate tests.
        try:
            if supply._instr is not None:
                supply._instr.close()
        finally:
            supply._instr = None
        if failures:
            raise failures[0]
