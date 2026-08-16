"""
PARIKA Capability Executor Events

Defines immutable execution lifecycle events published by the
CapabilityExecutor.

These events describe capability execution progress and are published
through the EventBus. They contain only immutable execution metadata and
never expose backend-specific request or response objects.

`task_id` (Phase 3.5b) optionally correlates one execution's Started
event to its own Completed/Failed counterpart, and to the owning
`TaskManager` `Task.id`, when known -- matching `ProgressEvent.task_id`'s
existing documented meaning (`parika/core/utilities/progress.py`).
It is `None` when `CapabilityExecutor.execute()` is called without a
`task_id` (e.g. directly, outside `TaskManager`). This is purely
additive: existing callers/constructions are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)

from .execution_backend import ExecutionBackend


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class CapabilityExecutionStartedEvent:
    """
    Published immediately before capability execution begins.

    Attributes:
        capability_id:
            Identifier of the resolved Capability.

        capability_category:
            Category of the Capability being executed.

        backend:
            Execution backend selected by the CapabilityExecutor.

        task_id:
            Optional identifier of the owning `TaskManager` `Task`,
            when known (Phase 3.5b). `None` when execution was
            requested without one.
    """

    capability_id: str
    capability_category: CapabilityCategory
    backend: ExecutionBackend
    task_id: str | None = None


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class CapabilityExecutionCompletedEvent:
    """
    Published after capability execution completes successfully.

    Attributes:
        capability_id:
            Identifier of the executed Capability.

        capability_category:
            Category of the executed Capability.

        backend:
            Execution backend used by the CapabilityExecutor.

        duration_seconds:
            Total execution duration in seconds.

        task_id:
            Optional identifier of the owning `TaskManager` `Task`,
            when known (Phase 3.5b). `None` when execution was
            requested without one.
    """

    capability_id: str
    capability_category: CapabilityCategory
    backend: ExecutionBackend
    duration_seconds: float
    task_id: str | None = None


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class CapabilityExecutionFailedEvent:
    """
    Published when capability execution terminates with an error.

    Attributes:
        capability_id:
            Identifier of the Capability.

        capability_category:
            Category of the Capability.

        backend:
            Execution backend selected by the CapabilityExecutor.

        error_type:
            Name of the normalized error type.

        error_message:
            Human-readable error description.

        task_id:
            Optional identifier of the owning `TaskManager` `Task`,
            when known (Phase 3.5b). `None` when execution was
            requested without one.
    """

    capability_id: str
    capability_category: CapabilityCategory
    backend: ExecutionBackend
    error_type: str
    error_message: str
    task_id: str | None = None


__all__ = [
    "CapabilityExecutionStartedEvent",
    "CapabilityExecutionCompletedEvent",
    "CapabilityExecutionFailedEvent",
]