"""
PARIKA Brain Exceptions

Defines the exception hierarchy used by Brain.

All Brain-specific exceptions derive from BrainError.

Brain intentionally reports pipeline-level failures (planning
failures, execution failures) through BrainResponse rather than
raising, so that a caller always receives a coherent final response.
These exceptions are raised only for malformed input supplied directly
to Brain's public API.
"""

from __future__ import annotations


class BrainError(Exception):
    """
    Base exception for all Brain errors.
    """


class InvalidBrainRequestError(BrainError):
    """
    Raised when a supplied BrainRequest is structurally invalid.
    """


class ContextEngineUnavailableError(BrainError):
    """
    Raised when `assemble_context()`/`compact()` are called without
    their required optional dependency configured (e.g. no
    `memory_manager`/`knowledge_manager` was supplied at construction
    time). See
    docs/architecture/Intelligence_Foundation_Design.md section 7.
    """


class DependencyResolutionError(BrainError):
    """
    Raised when a dependency reference in a goal's inputs cannot be resolved.
    This occurs when:
    - The referenced goal does not exist
    - The referenced goal is not a declared dependency
    - The dependency result is unavailable
    - The referenced result field/path does not exist
    - The reference syntax is malformed
    """
