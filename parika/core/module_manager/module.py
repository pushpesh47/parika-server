"""
PARIKA Module

Defines the immutable runtime representation of a registered PARIKA
Module.

A Module combines a ModuleManifest with its corresponding ModuleDriver
and current operational state.

The Module is descriptive only and contains no lifecycle management,
registration logic, execution behavior, or business logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .driver import ModuleDriver
from .manifest import ModuleManifest
from .state import ModuleState


@dataclass(frozen=True, slots=True, kw_only=True)
class Module:
    """
    Immutable runtime representation of a registered Module.

    A Module represents a module that has been registered with the
    ModuleManager. It combines the module's immutable metadata,
    runtime driver, and current operational state.
    """

    id: str
    """
    Unique identifier of the module.

    This value should match the identifier defined by the associated
    ModuleManifest.
    """

    manifest: ModuleManifest
    """
    Immutable metadata describing the module.
    """

    driver: ModuleDriver
    """
    Runtime driver implementing the module's behavior.
    """

    state: ModuleState
    """
    Current operational state of the module.
    """