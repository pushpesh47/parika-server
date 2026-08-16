"""
Experience Module exceptions.

This is a Module-level exception hierarchy, not a Core one -- Experience
is deliberately not a Core component (see
docs/architecture/Intelligence_Foundation_Design.md section 6A).
"""

from __future__ import annotations


class ExperienceError(Exception):
    """Base exception for all Experience Module errors."""


class ExperienceAlreadyExistsError(ExperienceError):
    """Raised when registering an Experience whose id already exists."""


class ExperienceNotFoundError(ExperienceError):
    """Raised when a requested Experience cannot be found."""


class InvalidExperienceError(ExperienceError):
    """Raised when an Experience object fails validation."""


class ExperiencePersistenceError(ExperienceError):
    """Raised when an Experience cannot be persisted or restored."""
