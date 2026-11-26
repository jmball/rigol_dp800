# SPDX-License-Identifier: GPL-3.0-or-later

"""Public hardware driver and physical channel views."""

from importlib.metadata import PackageNotFoundError, version

# get version if package has been installed
try:
    __version__ = version("rigol_dp800")
except PackageNotFoundError:
    __version__ = "0.0.0"

from dp800.dp800 import InstrumentError as InstrumentError

from .channel import DP800Channel as DP800Channel
from .dp800 import DP800 as DP800
from .dp800 import ENCODING as ENCODING
from .dp800 import LANGUAGE_NAMES as LANGUAGE_NAMES
from .dp800 import NOT_CONNECTED_MESSAGE as NOT_CONNECTED_MESSAGE
from .dp800 import PROTOCOL_RESOURCE_SETTINGS as PROTOCOL_RESOURCE_SETTINGS
from .dp800 import READ_TERMINATION as READ_TERMINATION
from .dp800 import (
    SERIAL_PROTOCOL_RESOURCE_SETTINGS as SERIAL_PROTOCOL_RESOURCE_SETTINGS,
)
from .dp800 import SERIAL_TERMINATION as SERIAL_TERMINATION
from .dp800 import WRITE_TERMINATION as WRITE_TERMINATION
