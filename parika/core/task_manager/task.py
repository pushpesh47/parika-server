"""
PARIKA Task

Defines the mutable runtime Task managed by TaskManager.

A Task represents a single runtime execution of a Capability. It owns
the execution lifecycle state together with the associated execution
request, execution response, runtime timestamps, failure information,
and implementation-neutral runtime metadata.

Task is a mutable runtime object managed exclusively by TaskManager.
It carries runtime state only and contains no business logic.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .request import TaskRequest
from .response import TaskResponse
from .task_status import TaskStatus


@dataclass(
    slots=True,
    kw_only=True,
)
class Task:
    """
    Mutable runtime Task.

    A Task represents the runtime execution state of a single
    Capability. It is created, managed, and destroyed exclusively by
    TaskManager and contains no business logic.
    """

    id: str
    """
    Unique runtime identifier of the Task.
    """

    status: TaskStatus
    """
    Current execution state of the Task.
    """

    request: TaskRequest
    """
    Immutable execution request associated with the Task.
    """

    response: TaskResponse | None = None
    """
    Immutable execution response produced after successful execution.
    """

    execution_id: str | None = None
    """
    Optional identifier of the Workflow Execution associated with this
    Task.
    """

    step_id: str | None = None
    """
    Optional identifier of the originating Workflow Step.
    """

    parent_task_id: str | None = None
    """
    Optional identifier of the parent Task for hierarchical execution.
    """

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when the Task was created.
    """

    started_at: datetime | None = None
    """
    Timestamp when execution started.
    """

    completed_at: datetime | None = None
    """
    Timestamp when execution completed.
    """

    failure: BaseException | None = None
    """
    Exception that caused Task execution to fail, if any.
    """

    metadata: MutableMapping[str, Any] = field(
        default_factory=dict,
    )
    """
    Mutable implementation-neutral runtime metadata.

    TaskManager does not assign semantics to these values. The metadata
    may be updated during the Task lifecycle by TaskManager or future
    runtime components.
    """