"""
PARIKA Workflow Events

Defines the immutable event payloads published by WorkflowEngine.

WorkflowEngine publishes events through EventBus to notify other
components about workflow lifecycle changes and step execution
progress.

All events are immutable data containers and contain no business
logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowRegisteredEvent:
    """Published after a Workflow has been registered."""

    workflow_id: str
    """Identifier of the registered Workflow."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowUnregisteredEvent:
    """Published after a Workflow has been unregistered."""

    workflow_id: str
    """Identifier of the unregistered Workflow."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowExecutionEvent:
    """
    Base event for workflow execution lifecycle events.
    """

    workflow_id: str
    """Identifier of the Workflow."""

    execution_id: str
    """Identifier of the Execution."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowStartedEvent(WorkflowExecutionEvent):
    """Published when workflow execution starts."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowPausedEvent(WorkflowExecutionEvent):
    """Published when workflow execution pauses."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowResumedEvent(WorkflowExecutionEvent):
    """Published when workflow execution resumes."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowCompletedEvent(WorkflowExecutionEvent):
    """Published when workflow execution completes successfully."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowCancelledEvent(WorkflowExecutionEvent):
    """Published when workflow execution is cancelled."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowFailedEvent(WorkflowExecutionEvent):
    """Published when workflow execution fails."""

    failure_reason: str
    """Description of the failure."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowStepEvent(WorkflowExecutionEvent):
    """
    Base event for workflow step lifecycle events.
    """

    step_id: str
    """Identifier of the Step."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowStepStartedEvent(WorkflowStepEvent):
    """Published when execution of a Step starts."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowStepCompletedEvent(WorkflowStepEvent):
    """Published when execution of a Step completes successfully."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowStepFailedEvent(WorkflowStepEvent):
    """Published when execution of a Step fails."""

    failure_reason: str
    """Description of the failure."""