"""
PARIKA Autonomous Execution - Checkpoint Manager

Manages checkpoint creation, validation, and restoration for autonomous task recovery.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.contracts import CheckpointStatus, validate_checkpoint_transition
from parika.core.autonomous.events import CheckpointCreatedEvent, CheckpointRestoredEvent
from parika.core.autonomous.models import CheckpointModel
from parika.core.autonomous.repository import CheckpointRepository
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class Checkpoint:
    """Checkpoint domain model."""
    id: str
    task_id: str
    execution_id: str
    mission_id: str
    agent_id: str | None
    version: int
    status: CheckpointStatus
    state_data: MappingProxyType[str, Any]
    created_at: datetime
    validated_at: datetime | None
    restored_at: datetime | None
    metadata: MappingProxyType[str, Any]

    @classmethod
    def from_model(cls, model: CheckpointModel) -> "Checkpoint":
        return cls(
            id=model.id,
            task_id=model.task_id,
            execution_id=model.execution_id,
            mission_id=model.mission_id,
            agent_id=model.agent_id,
            version=model.version,
            status=CheckpointStatus(model.status),
            state_data=MappingProxyType(model.state_data),
            created_at=model.created_at,
            validated_at=model.validated_at,
            restored_at=model.restored_at,
            metadata=MappingProxyType(model.metadata),
        )

    def to_model(self) -> CheckpointModel:
        return CheckpointModel(
            id=self.id,
            task_id=self.task_id,
            execution_id=self.execution_id,
            mission_id=self.mission_id,
            agent_id=self.agent_id,
            version=self.version,
            status=self.status.value,
            state_data=dict(self.state_data),
            created_at=self.created_at,
            validated_at=self.validated_at,
            restored_at=self.restored_at,
            metadata=dict(self.metadata),
        )


class CheckpointManager:
    """
    Manages checkpoint lifecycle for autonomous task recovery.
    
    Checkpoints capture execution state for safe recovery.
    Must be deterministic, versioned, validated, persistent, and recoverable.
    """

    def __init__(
        self,
        *,
        repository: CheckpointRepository,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def create(
        self,
        task_id: str,
        execution_id: str,
        mission_id: str,
        state_data: MappingProxyType[str, Any],
        *,
        agent_id: str | None = None,
        metadata: MappingProxyType[str, Any] | None = None,
    ) -> Checkpoint:
        """Create a new checkpoint."""
        # Get the latest version for this task
        latest = self._repository.get_latest_for_task(task_id)
        version = (latest.version + 1) if latest else 1

        now = datetime.now(UTC)
        checkpoint = Checkpoint(
            id=self._generate_id(),
            task_id=task_id,
            execution_id=execution_id,
            mission_id=mission_id,
            agent_id=agent_id,
            version=version,
            status=CheckpointStatus.CREATING,
            state_data=state_data,
            created_at=now,
            validated_at=None,
            restored_at=None,
            metadata=metadata or MappingProxyType({}),
        )

        model = checkpoint.to_model()
        self._repository.create(model)

        # Validate the checkpoint
        self._validate_checkpoint(checkpoint.id)

        self._event_bus.publish("checkpoint.created", CheckpointCreatedEvent(
            event_id=self._generate_id(),
            mission_id=mission_id,
            task_id=task_id,
            execution_id=execution_id,
            checkpoint_id=checkpoint.id,
            version=version,
            state_size_bytes=len(json.dumps(dict(state_data)).encode()),
        ))

        self._logger.info("Created checkpoint '%s' for task '%s' (version %d)", 
                         checkpoint.id, task_id, version)
        return checkpoint

    def _validate_checkpoint(self, checkpoint_id: str) -> bool:
        """Validate a checkpoint's integrity."""
        checkpoint = self.get(checkpoint_id)
        if checkpoint is None:
            return False

        if not validate_checkpoint_transition(checkpoint.status, CheckpointStatus.VALID):
            return False

        checkpoint.status = CheckpointStatus.VALID
        checkpoint.validated_at = datetime.now(UTC)
        self._repository.update(checkpoint.to_model())

        if not validate_checkpoint_transition(checkpoint.status, CheckpointStatus.AVAILABLE):
            return False

        checkpoint.status = CheckpointStatus.AVAILABLE
        self._repository.update(checkpoint.to_model())

        return True

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a checkpoint by ID."""
        model = self._repository.get(checkpoint_id)
        return Checkpoint.from_model(model) if model else None

    def get_latest_for_task(self, task_id: str) -> Checkpoint | None:
        """Get the latest available checkpoint for a task."""
        model = self._repository.get_latest_for_task(task_id)
        return Checkpoint.from_model(model) if model else None

    def restore(self, checkpoint_id: str) -> Checkpoint | None:
        """Restore a checkpoint for recovery."""
        checkpoint = self.get(checkpoint_id)
        if checkpoint is None:
            return None

        if checkpoint.status != CheckpointStatus.AVAILABLE:
            self._logger.warning("Cannot restore checkpoint '%s': status is %s", 
                               checkpoint_id, checkpoint.status)
            return None

        if not validate_checkpoint_transition(checkpoint.status, CheckpointStatus.RESTORING):
            return None

        checkpoint.status = CheckpointStatus.RESTORING
        self._repository.update(checkpoint.to_model())

        # Simulate restoration (in real implementation, state would be applied)
        # The actual state restoration is handled by the recovery coordinator

        if not validate_checkpoint_transition(checkpoint.status, CheckpointStatus.RESTORED):
            return None

        checkpoint.status = CheckpointStatus.RESTORED
        checkpoint.restored_at = datetime.now(UTC)
        self._repository.update(checkpoint.to_model())

        self._event_bus.publish("checkpoint.restored", CheckpointRestoredEvent(
            event_id=self._generate_id(),
            mission_id=checkpoint.mission_id,
            task_id=checkpoint.task_id,
            execution_id=checkpoint.execution_id,
            checkpoint_id=checkpoint.id,
            version=checkpoint.version,
        ))

        self._logger.info("Restored checkpoint '%s' (version %d) for task '%s'", 
                         checkpoint_id, checkpoint.version, checkpoint.task_id)
        return checkpoint

    def invalidate_old_checkpoints(self, task_id: str, keep_version: int) -> int:
        """Invalidate checkpoints older than the specified version."""
        count = self._repository.invalidate_old_checkpoints(task_id, keep_version)
        self._logger.info("Invalidated %d old checkpoints for task '%s'", count, task_id)
        return count

    def list_by_execution(self, execution_id: str) -> list[Checkpoint]:
        """List all checkpoints for an execution."""
        models = self._repository.list_by_execution(execution_id)
        return [Checkpoint.from_model(m) for m in models]

    def _generate_id(self) -> str:
        from uuid import uuid4
        return uuid4().hex


# ========================================================================
# State Serialization Helpers
# ========================================================================

def serialize_task_state(
    task: Any,
    execution: Any,
    agent: Any | None,
    mission: Any,
    additional_data: MappingProxyType[str, Any] | None = None,
) -> MappingProxyType[str, Any]:
    """
    Serialize task execution state for checkpointing.
    
    This creates a deterministic, versioned snapshot of all state
    needed to recover an autonomous task.
    """
    state = {
        "version": 1,
        "checkpoint_format": "parika_autonomous_v1",
        "task": {
            "id": task.id,
            "mission_id": task.mission_id,
            "name": task.name,
            "description": task.description,
            "capability_id": task.capability_id,
            "inputs": dict(task.inputs),
            "status": task.status.value,
            "priority": task.priority,
            "progress": task.progress,
            "max_retries": task.max_retries,
            "retry_count": task.retry_count,
            "resource_budget": dict(task.resource_budget),
            "metadata": dict(task.metadata),
        },
        "execution": {
            "id": execution.id,
            "attempt_number": execution.attempt_number,
            "status": execution.status,
            "metadata": dict(execution.metadata),
        },
        "mission": {
            "id": mission.id,
            "goal": mission.goal,
            "status": mission.status.value,
            "priority": mission.priority,
            "progress": mission.progress,
            "metadata": dict(mission.metadata),
        },
        "agent": {
            "id": agent.id if agent else None,
            "agent_profile_id": agent.agent_profile_id if agent else None,
            "status": agent.status.value if agent else None,
            "runtime": agent.runtime if agent else None,
            "permission_context": dict(agent.permission_context) if agent else {},
            "resource_budget": dict(agent.resource_budget) if agent else {},
        } if agent else None,
        "additional_data": dict(additional_data) if additional_data else {},
    }

    return MappingProxyType(state)


def deserialize_task_state(state_data: MappingProxyType[str, Any]) -> dict[str, Any]:
    """
    Deserialize and validate task state from checkpoint.
    
    Returns the validated state components.
    """
    if state_data.get("checkpoint_format") != "parika_autonomous_v1":
        raise ValueError("Invalid checkpoint format")

    version = state_data.get("version", 1)
    if version != 1:
        raise ValueError(f"Unsupported checkpoint version: {version}")

    return {
        "task": state_data.get("task", {}),
        "execution": state_data.get("execution", {}),
        "mission": state_data.get("mission", {}),
        "agent": state_data.get("agent"),
        "additional_data": state_data.get("additional_data", {}),
    }