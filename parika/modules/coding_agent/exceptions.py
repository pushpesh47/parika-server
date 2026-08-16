"""
PARIKA Coding Agent - Exceptions
"""

from __future__ import annotations


class CodingAgentError(Exception):
    """Base exception for every Coding Agent failure."""


class CodingPlanParsingError(CodingAgentError):
    """
    Raised when the model's decomposition response cannot be parsed
    into a structured `CodingPlan`.
    """


class CodingPlanValidationError(CodingAgentError):
    """
    Raised by the "review before modification" plan-validation gate
    (see
    docs/development/Module_Guide.md
    section 8.3.3) when a plan names an unknown/disabled capability, a
    path outside the authorized roots, or would exceed the configured
    reentrancy depth.
    """


class CodingAgentDepthExceededError(CodingAgentError):
    """
    Raised when a plan step would recurse into `coding.execute_task`
    beyond `[coding_agent].default_max_depth` (see section 8.7).
    """


class CodingAgentValidationRunFailedError(CodingAgentError):
    """
    Raised when `[coding_agent].require_test_run = true` and the
    executed test step's exit code was non-zero.
    """


class UnknownCodingAgentError(CodingAgentError):
    """
    Raised by `CodingAgentRegistry.get()` when the requested agent id
    is not registered.
    """
