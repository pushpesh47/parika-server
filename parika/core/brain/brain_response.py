"""
PARIKA Brain Response

Defines the immutable BrainResponse produced by Brain for a
BrainRequest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .goal_result import GoalResult


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class BrainResponse:
    """
    Immutable final response produced by Brain.

    A BrainResponse reports the per-Goal outcome of supervising a
    BrainRequest to completion, together with an overall success
    indicator.
    """

    request_id: str
    """
    Identifier of the originating BrainRequest.
    """

    plan_id: str | None
    """
    Identifier of the ExecutionPlan produced for this request.

    None when planning itself failed before a plan could be produced.
    """

    results: tuple[GoalResult, ...]
    """
    Per-Goal outcomes, in planned execution order.
    """

    planning_failure: BaseException | None = None
    """
    Exception raised while producing the ExecutionPlan, if planning
    failed before any Goal could be attempted.
    """

    completed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when this response was produced.
    """

    @property
    def succeeded(self) -> bool:
        """
        Whether every Goal in this request completed successfully.

        Returns False if planning failed entirely.
        """

        if self.planning_failure is not None:
            return False

        return all(result.succeeded for result in self.results)
