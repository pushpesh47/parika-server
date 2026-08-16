"""
PARIKA Goal Result

Defines the immutable GoalResult produced by Brain for a single Goal
within a supervised BrainRequest.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class GoalResult:
    """
    Immutable outcome of supervising a single Goal to completion.

    Exactly one of `response` or `failure` is populated when the Goal
    was attempted. Neither is populated when the Goal was skipped
    because one of its dependencies failed.
    """

    goal_id: str
    """
    Identifier of the Goal this result was produced for.
    """

    task_id: str | None
    """
    Identifier of the Task created for this Goal.

    None when the Goal was skipped before a Task could be created.
    """

    status: TaskStatus | None
    """
    Final TaskStatus of the created Task.

    None when the Goal was skipped.
    """

    response: TaskResponse | None = None
    """
    Successful execution response, if the Goal completed.
    """

    failure: BaseException | None = None
    """
    Exception raised while planning or executing the Goal, if any.
    """

    skipped: bool = False
    """
    Whether this Goal was skipped because a dependency failed.
    """

    skip_reason: str | None = None
    """
    Human-readable explanation of why the Goal was skipped, if
    `skipped` is True.
    """

    @property
    def succeeded(self) -> bool:
        """
        Whether this Goal completed successfully.
        """

        return (
            not self.skipped
            and self.status is TaskStatus.COMPLETED
            and self.failure is None
        )
