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


@pytest.fixture
def hardware(bench_config, visa_manager):
    manager = visa_manager
    supply = DP800()
    verified = False
    try:
        supply.connect(
            bench_config.resource_name,
            resource_manager=manager,
            timeout=bench_config.timeout,
            **bench_config.resource_options,
        )
        identity = supply.identity
        assert len(identity) == 4
        assert (
            identity[1].strip().upper() == bench_config.model
        ), "Connected model differs from --hardware-model"
        verified = True
        for number in bench_config.physical_channels:
            supply.channels[number].output_enabled = False
        yield supply
    finally:
        failures = []
        if verified and supply._instr is not None:
            # Shut down every physical output even if a prior cleanup command fails.
            for number in bench_config.physical_channels:
                try:
                    supply.channels[number].output_enabled = False
                except Exception as error:
                    failures.append(error)
            for operation in (
                lambda: setattr(supply, "keylock_enabled", False),
                supply.set_local,
            ):
                try:
                    operation()
                except Exception as error:
                    failures.append(error)
        # Harness cleanup addresses actual channels. Production disconnect() also
        # writes to absent CH2/CH3 on smaller models; its own tests cover that.
        try:
            if supply._instr is not None:
                supply._instr.close()
        finally:
            supply._instr = None
        if failures:
            raise failures[0]
