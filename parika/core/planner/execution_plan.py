"""
PARIKA Execution Plan

Defines the immutable ExecutionPlan produced by Planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .plan_step import PlanStep


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class ExecutionPlan:
    """
    Immutable, dependency-ordered execution plan.

    An ExecutionPlan contains every PlanStep produced from a plan()
    call, ordered so that each step appears after every step it
    depends on. Planner does not execute the plan; execution belongs
    to TaskManager, WorkflowEngine, and CapabilityExecutor.
    """

    id: str
    """
    Unique identifier of this plan.
    """

    steps: tuple[PlanStep, ...]
    """
    Dependency-ordered PlanStep sequence.
    """

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when the plan was produced.
    """
