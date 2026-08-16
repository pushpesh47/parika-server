"""
PARIKA Module Events

Defines the immutable events published by the ModuleManager during the
lifecycle of registered Modules.

These events are descriptive only and contain no business logic or
behavior.
"""

from __future__ import annotations

from dataclasses import dataclass

from .module import Module
from .state import ModuleState


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleRegisteredEvent:
    """
    Published when a Module is registered with the ModuleManager.
    """

    module: Module
    """
    The registered Module.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleUnregisteredEvent:
    """
    Published when a Module is unregistered from the ModuleManager.
    """

    module: Module
    """
    The unregistered Module.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleLoadedEvent:
    """
    Published when a Module has been successfully started and becomes
    operational.
    """

    module: Module
    """
    The loaded Module.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleUnloadedEvent:
    """
    Published when a Module has been successfully stopped.
    """

    module: Module
    """
    The unloaded Module.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleStateChangedEvent:
    """
    Published when the operational state of a Module changes.
    """

    module: Module
    """
    The Module whose state changed.
    """

    previous_state: ModuleState
    """
    Previous operational state.
    """

    current_state: ModuleState
    """
    Current operational state.
    """