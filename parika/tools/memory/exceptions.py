"""
PARIKA Memory Tool exceptions.
"""

from __future__ import annotations


class MemoryToolError(Exception):
    """Base exception for all Memory Tool errors."""


class InvalidMemoryToolArgumentError(MemoryToolError):
    """Raised when a required or malformed argument is supplied."""
