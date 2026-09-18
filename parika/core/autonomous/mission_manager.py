"""
PARIKA Autonomous Execution - Mission Manager

Manages the lifecycle of autonomous missions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.contracts import MissionStatus, validate_mission_transition
from parika.core.autonomous.events import (
    MissionCreatedEvent,
    MissionStartedEvent,
    MissionProgressEvent,
    MissionCompletedEvent,
    MissionFailedEvent,
    MissionCancelledEvent,
    MissionPausedEvent,
    MissionResumedEvent,
)
from parika.core.autonomous.models import MissionModel
from parika.core.autonomous.repository import MissionRepository
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class Mission:
    """Mission domain model."""
    id: str
    goal: str
    status: MissionStatus
    priority: int
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    deadline: datetime | None
    progress: float
    metadata: MappingProxyType[str, Any]
    failure: str | None
    result: MappingProxyType[str, Any] | None

    @classmethod
    def from_model(cls, model: MissionModel) -> "Mission":
        return cls(
            id=model.id,
            goal=model.goal,
            status=MissionStatus(model.status),
            priority=model.priority,
            created_at=model.created_at,
            started_at=model.started_at,
            updated_at=model.updated_at,
            completed_at=model.completed_at,
            deadline=model.deadline,
            progress=model.progress,
            metadata=MappingProxyType(model.mission_metadata),
            failure=model.failure,
            result=MappingProxyType(model.result) if model.result else None,
        )

    def to_model(self) -> MissionModel:
        return MissionModel(
            id=self.id,
            goal=self.goal,
            status=self.status.value,
            priority=self.priority,
            created_at=self.created_at,
            started_at=self.started_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
            deadline=self.deadline,
            progress=self.progress,
            metadata=dict(self.metadata),
            failure=self.failure,
            result=dict(self.result) if self.result else None,
        )


class MissionManager:
    """
    Manages autonomous mission lifecycle.
    
    Provides persistence, state transitions, and event publishing for missions.
    """

    def __init__(
        self,
        *,
        repository: MissionRepository,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def create(
        self,
        goal: str,
        *,
        priority: int = 0,
        deadline: datetime | None = None,
        metadata: MappingProxyType[str, Any] | None = None,
    ) -> Mission:
        """Create a new mission."""
        now = datetime.now(UTC)
        mission = Mission(
            id=self._generate_id(),
            goal=goal,
            status=MissionStatus.CREATED,
            priority=priority,
            created_at=now,
            started_at=None,
            updated_at=now,
            completed_at=None,
            deadline=deadline,
            progress=0.0,
            metadata=metadata or MappingProxyType({}),
            failure=None,
            result=None,
        )

        model = mission.to_model()
        self._repository.create(model)

        self._event_bus.publish("mission.created", MissionCreatedEvent(
            event_id=self._generate_id(),
            event_type="mission.created",
            mission_id=mission.id,
            goal=goal,
            priority=priority,
            deadline=deadline,
        ))

        self._logger.info("Created mission '%s': %s", mission.id, goal)
        return mission

    def plan(self, mission_id: str) -> Mission | None:
        """Transition mission to PLANNING (CREATED -> PLANNING)."""
        mission = self.get(mission_id)
        if mission is None:
            return None

        if not validate_mission_transition(mission.status, MissionStatus.PLANNING):
            self._logger.warning(
                "Invalid mission transition from %s to PLANNING for mission %s",
                mission.status, mission_id
            )
            return None

        mission.status = MissionStatus.PLANNING
        mission.updated_at = datetime.now(UTC)

        self.update(mission)

        self._logger.info("Planned mission '%s'", mission_id)
        return mission

    def get(self, mission_id: str) -> Mission | None:
        """Get a mission by ID."""
        model = self._repository.get(mission_id)
        return Mission.from_model(model) if model else None

    def update(self, mission: Mission) -> Mission:
        """Update a mission."""
        mission.updated_at = datetime.now(UTC)
        model = mission.to_model()
        self._repository.update(model)
        return mission

    def delete(self, mission_id: str) -> bool:
        """Delete a mission."""
        return self._repository.delete(mission_id)

    def start(self, mission_id: str) -> Mission | None:
        """Start a mission (transition to RUNNING)."""
        mission = self.get(mission_id)
        if mission is None:
            return None

        if not validate_mission_transition(mission.status, MissionStatus.RUNNING):
            self._logger.warning(
                "Invalid mission transition from %s to RUNNING for mission %s",
                mission.status, mission_id
            )
            return None

        mission.status = MissionStatus.RUNNING
        mission.started_at = datetime.now(UTC)
        mission.updated_at = datetime.now(UTC)

        self.update(mission)

        self._event_bus.publish("mission.started", MissionStartedEvent(
            event_id=self._generate_id(),
            event_type="mission.started",
            mission_id=mission.id,
        ))

        self._logger.info("Started mission '%s'", mission_id)
        return mission

    def update_progress(self, mission_id: str, progress: float, message: str | None = None) -> Mission | None:
        """Update mission progress."""
        mission = self.get(mission_id)
        if mission is None:
            return None

        mission.progress = max(0.0, min(1.0, progress))
        mission.updated_at = datetime.now(UTC)

        self.update(mission)

        self._event_bus.publish("mission.progress", MissionProgressEvent(
            event_id=self._generate_id(),
            event_type="mission.progress",
            mission_id=mission.id,
            progress=mission.progress,
            message=message,
        ))

        return mission

    def complete(self, mission_id: str, result: MappingProxyType[str, Any] | None = None) -> Mission | None:
        """Complete a mission successfully."""
        mission = self.get(mission_id)
        if mission is None:
            return None

        if not validate_mission_transition(mission.status, MissionStatus.COMPLETED):
            self._logger.warning(
                "Invalid mission transition from %s to COMPLETED for mission %s",
                mission.status, mission_id
            )
            return None

        mission.status = MissionStatus.COMPLETED
        mission.completed_at = datetime.now(UTC)
        mission.progress = 1.0
        mission.result = result
        mission.updated_at = datetime.now(UTC)

        self.update(mission)

        self._event_bus.publish("mission.completed", MissionCompletedEvent(
            event_id=self._generate_id(),
            event_type="mission.completed",
            mission_id=mission.id,
            result=result,
        ))

        self._logger.info("Completed mission '%s'", mission_id)
        return mission

    def fail(self, mission_id: str, failure: str, recoverable: bool = True) -> Mission | None:
        """Mark a mission as failed."""
        mission = self.get(mission_id)
        if mission is None:
            return None

        if not validate_mission_transition(mission.status, MissionStatus.FAILED):
            self._logger.warning(
                "Invalid mission transition from %s to FAILED for mission %s",
                mission.status, mission_id
            )
            return None

        mission.status = MissionStatus.FAILED
        mission.failure = failure
        mission.completed_at = datetime.now(UTC)
        mission.updated_at = datetime.now(UTC)

        self.update(mission)

        self._event_bus.publish("mission.failed", MissionFailedEvent(
            event_id=self._generate_id(),
            event_type="mission.failed",
            mission_id=mission.id,
            failure=failure,
            recoverable=recoverable,
        ))

        self._logger.error("Mission '%s' failed: %s", mission_id, failure)
        return mission

    def cancel(self, mission_id: str, reason: str | None = None) -> Mission | None:
        """Cancel a mission."""
        mission = self.get(mission_id)
        if mission is None:
            return None

        if not validate_mission_transition(mission.status, MissionStatus.CANCELLED):
            self._logger.warning(
                "Invalid mission transition from %s to CANCELLED for mission %s",
                mission.status, mission_id
            )
            return None

        mission.status = MissionStatus.CANCELLED
        mission.completed_at = datetime.now(UTC)
        mission.updated_at = datetime.now(UTC)

        self.update(mission)

        self._event_bus.publish("mission.cancelled", MissionCancelledEvent(
            event_id=self._generate_id(),
            event_type="mission.cancelled",
            mission_id=mission.id,
            reason=reason,
        ))

        self._logger.info("Cancelled mission '%s': %s", mission_id, reason)
        return mission

    def pause(self, mission_id: str, reason: str | None = None) -> Mission | None:
        """Pause a mission."""
        mission = self.get(mission_id)
        if mission is None:
            return None

        if not validate_mission_transition(mission.status, MissionStatus.PAUSED):
            return None

        mission.status = MissionStatus.PAUSED
        mission.updated_at = datetime.now(UTC)

        self.update(mission)

        self._event_bus.publish("mission.paused", MissionPausedEvent(
            event_id=self._generate_id(),
            event_type="mission.paused",
            mission_id=mission.id,
            reason=reason,
        ))

        return mission

    def resume(self, mission_id: str) -> Mission | None:
        """Resume a paused mission."""
        mission = self.get(mission_id)
        if mission is None:
            return None

        if not validate_mission_transition(mission.status, MissionStatus.RUNNING):
            return None

        mission.status = MissionStatus.RUNNING
        mission.updated_at = datetime.now(UTC)

        self.update(mission)

        self._event_bus.publish("mission.resumed", MissionResumedEvent(
            event_id=self._generate_id(),
            event_type="mission.resumed",
            mission_id=mission.id,
        ))

        return mission

    def list_active(self) -> list[Mission]:
        """List all active missions."""
        models = self._repository.list_active()
        return [Mission.from_model(m) for m in models]

    def list_by_status(self, status: MissionStatus) -> list[Mission]:
        """List missions by status."""
        models = self._repository.list_by_status(status.value)
        return [Mission.from_model(m) for m in models]

    def _generate_id(self) -> str:
        from uuid import uuid4
        return uuid4().hex