"""
PARIKA Workflow Execution

Defines the mutable Execution model managed by WorkflowEngine.

An Execution represents a single runtime execution of a registered
Workflow. It maintains only the mutable execution state required during
workflow execution.

An Execution is created and managed exclusively by WorkflowEngine and
contains no execution logic or business behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .execution_status import ExecutionStatus


@dataclass(slots=True, kw_only=True)
class Execution:
    """
    Mutable runtime execution of a Workflow.

    An Execution represents a single runtime instance of a registered
    Workflow. It contains only the mutable execution state required by
    WorkflowEngine and carries no business logic.
    """

    id: str
    """Unique identifier of the Execution."""

    workflow_id: str
    """Identifier of the Workflow being executed."""

    status: ExecutionStatus
    """Current execution status."""

    context_id: str
    """Identifier of the associated execution Context."""

    current_step_id: str | None
    """Identifier of the currently executing Step."""

    parent_execution_id: str | None = None
    """Identifier of the parent Execution for nested workflows."""

    created_at: datetime
    """Timestamp when the Execution was created."""

    started_at: datetime | None = None
    """Timestamp when execution began."""

    completed_at: datetime | None = None
    """Timestamp when execution completed."""

    failure_reason: str | None = None
    """Description of the terminal failure, if execution failed."""