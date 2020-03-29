"""Rigol DP800 series power supply control library.

The full instrument manual, including the programming guide, can be found at
https://www.rigolna.com/products/dc-power-loads/dp800/.
"""
import logging
import warnings

import visa


logging.captureWarnings(True)
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

rm = visa.ResourceManager()


class dp800:
    """Rigol DP800 series power supply instrument.

    Use the `connect()` method to open a connection to the instrument and instantiate
    the VISA resource attribute `instr` for an dp800 instance. This attribute can be
    used to access all of the PyVISA attributes and methods for the resource.
    """

    def __init__(self, check_errors=True):
        """Initialise VISA resource for instrument.

        Parameters
        ----------
        check_errors : bool, optional
            Check instrument error status after every command.
        """
        self.check_errors = check_errors

    def connect(
        self,
        resource_name,
        reset=True,
        set_default_configuration=True,
        **resource_kwargs,
    ):
        """Conntect to the instrument.

        Parameters
        ----------
        resource_name : str
            Full VISA resource name, e.g. "ASRL2::INSTR", "GPIB0::14::INSTR" etc. See
            https://pyvisa.readthedocs.io/en/latest/introduction/names.html for more
            info on correct formatting for resource names.
        reset : bool, optional
            Reset the instrument to the built-in default configuration.
        set_default_configuration : bool, optional
            If True, set all configuration settings to defaults defined in the
            `set_configuraiton` method.
        resource_kwargs : dict
            Keyword arguments to be used to change instrument attributes after
            construction.
        """
        self.instr = rm.open_resource(resource_name, **resource_kwargs)
        if reset is True:
            self.reset()
        if set_default_configuration is True:
            self.set_configuration()

    def disconnect(self):
        """Disconnect the instrument."""
        self.instr.close()

    def set_configuration(self):
        """Set the instrument configuration."""
        pass

    def get_configuration(self):
        """Get the instrument configuration."""
        pass

    def reset(self):
        """Reset the instrument to built-in default configuration."""
        pass
