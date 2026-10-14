# SPDX-License-Identifier: GPL-3.0-or-later

from importlib.metadata import PackageNotFoundError, version

# get version if package has been installed
try:
    __version__ = version("rigol_dp800")
except PackageNotFoundError:
    __version__ = "0.0.0"

from .virtual_dp800 import *
from dp800.channel import DP800Channel as DP800Channel
