# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared pytest fixtures and opt-in hardware configuration."""

import pytest

from tests.fakes import make_fake_visa


def pytest_addoption(parser):
    group = parser.getgroup("DP800 hardware")
    group.addoption("--visa-resource", help="VISA address; enables real hardware tests")
    group.addoption("--visa-backend", help="PyVISA backend, for example @py")
    group.addoption(
        "--visa-timeout", type=int, default=5000, help="I/O timeout in milliseconds"
    )
    group.addoption(
        "--visa-options",
        default="{}",
        help='Additional PyVISA opening options/attributes as a JSON object, e.g. {"baud_rate": 9600}',
    )
    group.addoption("--hardware-model", help="Expected model, for example DP832A")
    group.addoption(
        "--hardware-channels",
        help="Comma-separated channels to exercise; defaults to all physical channels",
    )
    group.addoption(
        "--hardware-voltage",
        type=float,
        default=1.0,
        help="Test voltage magnitude, 0 < V <= 5",
    )
    group.addoption(
        "--hardware-current",
        type=float,
        default=0.01,
        help="Test current limit, 0 < A <= 0.1",
    )
    group.addoption(
        "--hardware-allow-output",
        action="store_true",
        help="Allow output-on tests on an isolated bench",
    )
    group.addoption(
        "--hardware-trigger",
        action="store_true",
        help="Exercise triggering on a supply with the trigger option installed",
    )
    group.addoption(
        "--hardware-reset",
        action="store_true",
        help="Allow reset; previous configuration is lost",
    )
    group.addoption(
        "--hardware-save-slot",
        type=int,
        help="Allow overwriting and recalling this saved setup slot (1-9)",
    )
    group.addoption(
        "--hardware-license",
        help="Install this instrument-specific option license; persistent change",
    )


def pytest_configure(config):
    from tests.hardware.support import HardwareConfig

    # Validate before collection or any I/O, including for --collect-only.
    config._dp800_hardware = HardwareConfig.from_pytest(config)


def pytest_collection_modifyitems(config, items):
    if config.getoption("--visa-resource"):
        return
    skip = pytest.mark.skip(
        reason="real hardware requires --visa-resource and --hardware-model"
    )
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def fake_visa():
    """An independent driver, fake resource, and mocked resource manager."""
    return make_fake_visa()
