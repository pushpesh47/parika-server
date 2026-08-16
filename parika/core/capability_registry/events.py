"""
Capability registry events.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityRegistered:
    """
    Published after a capability has been successfully registered.
    """

    capability_id: str


@dataclass(frozen=True, slots=True)
class CapabilityUnregistered:
    """
    Published after a capability has been successfully unregistered.
    """

    capability_id: str


@dataclass(frozen=True, slots=True)
class CapabilityEnabled:
    """
    Published after a capability has been enabled.
    """

    capability_id: str


@dataclass(frozen=True, slots=True)
class CapabilityDisabled:
    """
    Published after a capability has been disabled.
    """

    capability_id: str