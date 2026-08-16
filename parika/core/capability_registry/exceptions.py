"""
Capability registry exceptions.
"""


class CapabilityRegistryError(Exception):
    """
    Base exception for all capability registry errors.
    """


class CapabilityAlreadyRegisteredError(CapabilityRegistryError):
    """
    Raised when attempting to register a capability whose ID already exists.
    """


class CapabilityNotFoundError(CapabilityRegistryError):
    """
    Raised when a requested capability cannot be found.
    """


class InvalidCapabilityError(CapabilityRegistryError):
    """
    Raised when a capability definition is invalid.
    """