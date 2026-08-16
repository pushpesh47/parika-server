"""
PARIKA Plan Step

Defines the immutable PlanStep produced by Planner for a single Goal.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.capability_executor.request import (
    CapabilityExecutionRequest,
)


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class PlanStep:
    """
    Immutable execution step produced from a single Goal.

    A PlanStep pairs the originating goal identifier with the fully
    prepared CapabilityExecutionRequest ready to be handed to
    TaskManager and CapabilityExecutor.
    """

    goal_id: str
    """
    Identifier of the Goal this step was produced from.
    """

    execution_request: CapabilityExecutionRequest
    """
    Fully prepared execution request for this step.
    """

    depends_on: tuple[str, ...]
    """
    Identifiers of other Goals that must execute before this step.
    """
