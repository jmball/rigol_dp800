# SPDX-License-Identifier: GPL-3.0-or-later

"""Distribution version lookup works for installed and source-only imports."""

import importlib
import importlib.metadata
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("package_name", ["dp800", "virtual_dp800"])
@pytest.mark.parametrize("installed", [True, False], ids=["installed", "source-only"])
def test_package_version(package_name, installed, monkeypatch):
    package = importlib.import_module(package_name)
    lookup = Mock(return_value="1.2.3")
    if not installed:
        lookup.side_effect = importlib.metadata.PackageNotFoundError("rigol_dp800")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(importlib.metadata, "version", lookup)
            importlib.reload(package)
            assert package.__version__ == ("1.2.3" if installed else "0.0.0")
            lookup.assert_called_once_with("rigol_dp800")
    finally:
        importlib.reload(package)
