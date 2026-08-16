"""
PARIKA Capability Executor Exceptions.

Defines exceptions raised by the CapabilityExecutor component.
"""

from __future__ import annotations


class CapabilityExecutionError(Exception):
    """
    Base exception for all CapabilityExecutor errors.
    """


class InvalidExecutionTargetError(CapabilityExecutionError):
    """
    Raised when an execution target is invalid or unsupported.
    """


class InvalidCapabilityExecutionRequestError(CapabilityExecutionError):
    """
    Raised when a capability execution request is invalid.
    """