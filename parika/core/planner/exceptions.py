"""
PARIKA Planner Exceptions

Defines the exception hierarchy used by Planner.

All Planner-specific exceptions derive from PlannerError.
"""

from __future__ import annotations


class PlannerError(Exception):
    """
    Base exception for all Planner errors.
    """


class InvalidGoalError(PlannerError):
    """
    Raised when a supplied Goal is structurally invalid.
    """


class DuplicateGoalIdError(PlannerError):
    """
    Raised when two Goals within the same planning request share the
    same identifier.
    """


class UnknownGoalDependencyError(PlannerError):
    """
    Raised when a Goal declares a dependency on a Goal identifier that
    does not exist within the same planning request.
    """


class CyclicDependencyError(PlannerError):
    """
    Raised when Goal dependencies form a cycle.
    """


class GoalDeniedByPolicyError(PlannerError):
    """
    Raised when PolicyEngine denies a Goal.
    """


class NoAvailableToolError(PlannerError):
    """
    Raised when a Goal resolves to the TOOL execution backend but no
    enabled Tool implements the requested Capability.
    """


class NoAvailableProviderModelError(PlannerError):
    """
    Raised when a Goal resolves to the PROVIDER execution backend but
    no enabled Provider exposes a Model satisfying the requested
    Capability.
    """


class MissingProviderRequestBuilderError(PlannerError):
    """
    Raised when a Goal resolves to the PROVIDER execution backend but
    does not supply a provider_request_builder.
    """
