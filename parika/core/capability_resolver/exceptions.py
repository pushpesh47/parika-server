"""
Capability resolver exceptions.
"""

from __future__ import annotations


class CapabilityResolutionError(Exception):
    """
    Base exception for capability resolution errors.
    """


class CapabilityDisabledError(CapabilityResolutionError):
    """
    Raised when attempting to resolve a disabled capability.
    """