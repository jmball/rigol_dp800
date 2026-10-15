# SPDX-License-Identifier: GPL-3.0-or-later

"""Bench configuration, separate from the driver's deliberately generic channels.

Model/channel applicability follows the Rigol DP800 programming guide:
https://www.batronix.com/pdf/Rigol/ProgrammingGuide/DP800_ProgrammingGuide_EN.pdf
"""

from dataclasses import dataclass
import json
import math

import pytest

CHANNEL_COUNTS = {
    "DP811": 1,
    "DP813": 1,
    "DP821": 2,
    "DP822": 2,
    "DP831": 3,
    "DP832": 3,
}


@dataclass(frozen=True)
class HardwareConfig:
    resource_name: str
    model: str
    channels: tuple[int, ...]
    voltage: float
    current: float
    timeout: int
    backend: str | None
    resource_options: dict
    allow_output: bool
    trigger: bool
    reset: bool
    save_slot: int | None
    license: str | None

    @property
    def base_model(self):
        return self.model.removesuffix("A")

    @property
    def physical_channels(self):
        return tuple(range(1, CHANNEL_COUNTS[self.base_model] + 1))

    @property
    def sense_channels(self):
        if self.base_model in {"DP811", "DP813"}:
            return (1,)
        if self.base_model in {"DP821", "DP822"}:
            return (2,)
        return ()

    def channel_voltage(self, channel):
        # DP831 CH3 is the negative output.
        return (
            -self.voltage
            if self.base_model == "DP831" and channel == 3
            else self.voltage
        )

    @classmethod
    def from_pytest(cls, config):
        resource = config.getoption("--visa-resource")
        if not resource:
            return None
        model = (config.getoption("--hardware-model") or "").upper()
        base = model.removesuffix("A")
        if base not in CHANNEL_COUNTS:
            raise pytest.UsageError(
                "--hardware-model must specify a supported DP811/813/821/822/831/832 model (optionally A)"
            )
        raw_channels = config.getoption("--hardware-channels")
        try:
            channels = (
                tuple(int(value) for value in raw_channels.split(","))
                if raw_channels
                else tuple(range(1, CHANNEL_COUNTS[base] + 1))
            )
        except ValueError as error:
            raise pytest.UsageError(
                "--hardware-channels must be comma-separated integers"
            ) from error
        if (
            not channels
            or len(set(channels)) != len(channels)
            or any(
                value not in range(1, CHANNEL_COUNTS[base] + 1) for value in channels
            )
        ):
            raise pytest.UsageError(
                "--hardware-channels must contain unique physical channels for the model"
            )
        voltage, current = config.getoption("--hardware-voltage"), config.getoption(
            "--hardware-current"
        )
        if not math.isfinite(voltage) or not 0 < voltage <= 5:
            raise pytest.UsageError("--hardware-voltage must be finite and in (0, 5] V")
        if not math.isfinite(current) or not 0 < current <= 0.1:
            raise pytest.UsageError(
                "--hardware-current must be finite and in (0, 0.1] A"
            )
        timeout, slot = config.getoption("--visa-timeout"), config.getoption(
            "--hardware-save-slot"
        )
        try:
            resource_options = json.loads(config.getoption("--visa-options"))
        except (TypeError, ValueError) as error:
            raise pytest.UsageError("--visa-options must be a JSON object") from error
        if not isinstance(resource_options, dict):
            raise pytest.UsageError("--visa-options must be a JSON object")
        if {"resource_name", "resource_manager", "timeout"} & resource_options.keys():
            raise pytest.UsageError(
                "--visa-options cannot override resource_name/resource_manager/timeout; use the dedicated CLI arguments"
            )
        if timeout <= 0:
            raise pytest.UsageError("--visa-timeout must be positive")
        if slot is not None and not 1 <= slot <= 9:
            raise pytest.UsageError("--hardware-save-slot must be in 1-9")
        license = config.getoption("--hardware-license")
        if license is not None and (
            len(license) != 28 or not license.isascii() or not license.isalnum()
        ):
            raise pytest.UsageError(
                "--hardware-license must contain 28 ASCII letters or digits"
            )
        return cls(
            resource,
            model,
            channels,
            voltage,
            current,
            timeout,
            config.getoption("--visa-backend"),
            resource_options,
            config.getoption("--hardware-allow-output"),
            config.getoption("--hardware-trigger"),
            config.getoption("--hardware-reset"),
            slot,
            license,
        )
