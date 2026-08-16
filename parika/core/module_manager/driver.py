"""
PARIKA Module Driver

Defines the abstract runtime contract implemented by all PARIKA
Modules.

A ModuleDriver encapsulates the runtime behavior of a Module and is
responsible for starting and stopping the module.

The driver does not manage registration, lifecycle orchestration,
configuration loading, event publication, or capability registration.
Those responsibilities belong to the ModuleManager and other Core
components.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ModuleDriver(ABC):
    """
    Abstract base class for all PARIKA Module drivers.

    A ModuleDriver provides the runtime implementation of a Module.
    Concrete drivers are responsible for preparing the module for
    operation and releasing any acquired resources when the module is
    stopped.
    """

    @abstractmethod
    def start(self) -> None:
        """
        Start the module.

        This method prepares the module for operation. Any resources
        required by the module should be acquired during startup.

        Raises:
            Exception:
                If the module cannot be started successfully.
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """
        Stop the module.

        This method performs any cleanup required before the module is
        unloaded. All acquired resources should be released during
        shutdown.

        Raises:
            Exception:
                If the module cannot be stopped cleanly.
        """
        raise NotImplementedError