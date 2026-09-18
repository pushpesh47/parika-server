"""
PARIKA Experience Recorder

Subscribes to TaskManager's already-published `task.completed`/
`task.failed` events and translates them into Experience records.

No changes were needed to TaskManager or CapabilityExecutor's control
flow to support this -- both already publish the events this recorder
consumes (see docs/architecture/Intelligence_Foundation_Design.md
section 6A). This is the same "EventBus subscriber" extension point
the Model Selection Framework document itself names as the natural
home for future telemetry consumers.

`provider_id`/`model_id` are read from `task.response.metadata`
(populated by `CapabilityExecutor` only for provider-backed
capabilities -- see Phase 1 Completion Specification section 18) and
default to `None` for tool-backed capabilities or if that metadata is
ever absent; `ExperienceRule` already degrades gracefully to a neutral
score in that case, and its weight defaults to 0 (opt-in) regardless.
"""

from __future__ import annotations

from datetime import datetime, UTC
from uuid import uuid4

from parika.core.event_bus.event_bus import EventBus
from parika.core.task_manager.events import TaskCompletedEvent, TaskFailedEvent
from parika.core.task_manager.task_manager import (
    TASK_COMPLETED_EVENT,
    TASK_FAILED_EVENT,
)

from .experience import Experience
from .experience_outcome import ExperienceOutcome
from .experience_store import ExperienceStore
from parika.core.forensic_log import get_current_trace_id


class ExperienceRecorder:
    """
    EventBus subscriber that records Task outcomes as Experience data.

    An internal collaborator of the Experience Module -- not a second
    public entry point. Only `runtime.py` (the composition root) and
    this Module's own driver construct and wire it.
    """

    def __init__(self, event_bus: EventBus, experience_store: ExperienceStore) -> None:
        self._event_bus = event_bus
        self._experience_store = experience_store

    def initialize(self) -> None:
        """Subscribe to TaskManager's completion/failure events."""

        self._event_bus.subscribe(TASK_COMPLETED_EVENT, self._on_task_completed)
        self._event_bus.subscribe(TASK_FAILED_EVENT, self._on_task_failed)

    def shutdown(self) -> None:
        """Unsubscribe from TaskManager's events."""

        self._event_bus.unsubscribe(TASK_COMPLETED_EVENT, self._on_task_completed)
        self._event_bus.unsubscribe(TASK_FAILED_EVENT, self._on_task_failed)

    def _on_task_completed(self, event: Any) -> None:
        capability_id = getattr(event, 'capability_id', None)
        task_id = getattr(event, 'task_id', None)
        latency_ms: float | None = None
        provider_id: str | None = None
        model_id: str | None = None

        if hasattr(event, 'task'):
            task = event.task
            capability_id = task.request.capability_id if hasattr(task, 'request') else capability_id
            task_id = task.id if hasattr(task, 'id') else task_id
            if hasattr(task, 'response') and task.response is not None:
                if task.response.duration_seconds is not None:
                    latency_ms = task.response.duration_seconds * 1000.0
                if hasattr(task.response, 'metadata'):
                    provider_id = task.response.metadata.get("provider_id")
                    model_id = task.response.metadata.get("model_id")
        elif isinstance(event, dict):
            capability_id = event.get("capability_id") or capability_id
            task_id = event.get("task_id") or task_id

        if not capability_id:
            return

        # FORENSIC: Log experience registration
        trace_id = get_current_trace_id()
        if trace_id:
            from parika.core.forensic_log import log_experience_registration
            log_experience_registration(
                trace_id=trace_id,
                capability_id=capability_id,
                outcome="SUCCESS",
                provider_id=provider_id,
                model_id=model_id,
                latency_ms=latency_ms,
                task_succeeded=True,
                task_id=task_id,
            )

        self._experience_store.register(
            Experience(
                experience_id=uuid4().hex,
                capability_id=capability_id,
                outcome=ExperienceOutcome.SUCCESS,
                created_at=datetime.now(UTC),
                latency_ms=latency_ms,
                provider_id=provider_id,
                model_id=model_id,
            )
        )

    def _on_task_failed(self, event: TaskFailedEvent) -> None:
        # Handle both autonomous TaskFailedEvent (direct capability_id/task_id)
        # and normal TaskFailedEvent (nested task.request.capability_id / task.id)
        capability_id = getattr(event, 'capability_id', None)
        task_id = getattr(event, 'task_id', None)
        
        if capability_id is None and hasattr(event, 'task'):
            capability_id = event.task.request.capability_id
            task_id = event.task.id

        # FORENSIC: Log experience registration
        trace_id = get_current_trace_id()
        if trace_id:
            from parika.core.forensic_log import log_experience_registration
            log_experience_registration(
                trace_id=trace_id,
                capability_id=capability_id,
                outcome="FAILURE",
                provider_id=None,
                model_id=None,
                task_succeeded=False,
                task_id=task_id,
            )

        self._experience_store.register(
            Experience(
                experience_id=uuid4().hex,
                capability_id=capability_id,
                outcome=ExperienceOutcome.FAILURE,
                created_at=datetime.now(UTC),
            )
        )
