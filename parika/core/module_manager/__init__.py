"""
PARIKA Module Manager

Public interface for the ModuleManager component.
"""

from .driver import ModuleDriver
from .events import (
    ModuleLoadedEvent,
    ModuleRegisteredEvent,
    ModuleStateChangedEvent,
    ModuleUnloadedEvent,
    ModuleUnregisteredEvent,
)
from .exceptions import (
    DriverNotFoundError,
    ModuleAlreadyLoadedError,
    ModuleAlreadyRegisteredError,
    ModuleLoadError,
    ModuleManagerError,
    ModuleNotFoundError,
    ModuleNotLoadedError,
    ModuleUnloadError,
)
from .manifest import ModuleManifest
from .module import Module
from .module_manager import ModuleManager
from .state import ModuleState

__all__ = [
    "DriverNotFoundError",
    "Module",
    "ModuleAlreadyLoadedError",
    "ModuleAlreadyRegisteredError",
    "ModuleDriver",
    "ModuleLoadError",
    "ModuleLoadedEvent",
    "ModuleManager",
    "ModuleManagerError",
    "ModuleManifest",
    "ModuleNotFoundError",
    "ModuleNotLoadedError",
    "ModuleRegisteredEvent",
    "ModuleState",
    "ModuleStateChangedEvent",
    "ModuleUnloadError",
    "ModuleUnloadedEvent",
    "ModuleUnregisteredEvent",
]