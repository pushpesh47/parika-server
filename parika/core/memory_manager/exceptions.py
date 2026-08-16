"""
Memory manager exceptions.
"""

from __future__ import annotations


class MemoryManagerError(Exception):
    """
    Base exception for all memory manager errors.
    """


class MemoryAlreadyExistsError(MemoryManagerError):
    """
    Raised when attempting to register a memory whose ID already exists.
    """


class MemoryNotFoundError(MemoryManagerError):
    """
    Raised when a requested memory cannot be found.
    """


class InvalidMemoryError(MemoryManagerError):
    """
    Raised when a memory object fails validation.
    """


class MemoryPersistenceError(MemoryManagerError):
    """
    Raised when a memory cannot be persisted or restored.
    """