"""
PARIKA Autonomous Execution Events

Event definitions for autonomous execution lifecycle.
All events are immutable and carry correlation information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class AutonomousEvent:
    """
    Base class for all autonomous execution events.
    
    Provides correlation information to associate events with
    missions, tasks, agents, executions, and workers.
    """
    event_id: str
    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    # Correlation IDs
    mission_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    execution_id: str | None = None
    worker_id: str | None = None
    parent_task_id: str | None = None
    parent_agent_id: str | None = None
    
    # Additional context
    metadata: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))


# ========================================================================
# Mission Events
# ========================================================================

@dataclass(frozen=True, slots=True, kw_only=True)
class MissionCreatedEvent(AutonomousEvent):
    """Mission has been created and persisted."""
    goal: str
    priority: int
    deadline: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionStartedEvent(AutonomousEvent):
    """Mission has transitioned to RUNNING."""
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionProgressEvent(AutonomousEvent):
    """Mission progress has been updated."""
    progress: float
    message: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionCompletedEvent(AutonomousEvent):
    """Mission has completed successfully."""
    result: MappingProxyType[str, Any] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionFailedEvent(AutonomousEvent):
    """Mission has failed."""
    failure: str
    recoverable: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionCancelledEvent(AutonomousEvent):
    """Mission has been cancelled."""
    reason: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionPausedEvent(AutonomousEvent):
    """Mission has been paused."""
    reason: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionResumedEvent(AutonomousEvent):
    """Mission has been resumed."""
    pass


# ========================================================================
# Task Events
# ========================================================================

@dataclass(frozen=True, slots=True, kw_only=True)
class TaskCreatedEvent(AutonomousEvent):
    """Autonomous task has been created."""
    name: str
    description: str
    capability_id: str | None
    inputs: MappingProxyType[str, Any]
    priority: int
    max_retries: int
    resource_budget: MappingProxyType[str, Any]
    deadline: datetime | None = None
    provider_request_type: str | None = None
    task_category: str | None = None
    execution_requirements: MappingProxyType[str, Any] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskStartedEvent(AutonomousEvent):
    """Task has started execution."""
    attempt_number: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskProgressEvent(AutonomousEvent):
    """Task progress has been updated."""
    progress: float
    message: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskCompletedEvent(AutonomousEvent):
    """Task has completed successfully."""
    result: MappingProxyType[str, Any] | None = None
    attempt_number: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskFailedEvent(AutonomousEvent):
    """Task has failed."""
    failure: str
    attempt_number: int
    retry_eligible: bool = False
    retry_count: int = 0
    max_retries: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskCancelledEvent(AutonomousEvent):
    """Task has been cancelled."""
    reason: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskPausedEvent(AutonomousEvent):
    """Task has been paused."""
    reason: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskResumedEvent(AutonomousEvent):
    """Task has been resumed."""
    attempt_number: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskWaitingForDependencyEvent(AutonomousEvent):
    """Task is waiting for dependency completion."""
    dependency_task_id: str
    dependency_status: str


# ========================================================================
# Agent Events
# ========================================================================

@dataclass(frozen=True, slots=True, kw_only=True)
class AgentSpawnedEvent(AutonomousEvent):
    """Agent instance has been spawned."""
    agent_profile_id: str
    runtime: str
    permission_context: MappingProxyType[str, Any]
    resource_budget: MappingProxyType[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentStartedEvent(AutonomousEvent):
    """Agent instance has started execution."""
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentCompletedEvent(AutonomousEvent):
    """Agent instance has completed successfully."""
    result: MappingProxyType[str, Any] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentFailedEvent(AutonomousEvent):
    """Agent instance has failed."""
    failure: str


# ========================================================================
# Worker Events
# ========================================================================

@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerSpawnedEvent(AutonomousEvent):
    """Worker has been spawned."""
    heartbeat_interval_seconds: float
    timeout_seconds: float


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerStartedEvent(AutonomousEvent):
    """Worker has started execution."""
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerHeartbeatEvent(AutonomousEvent):
    """Worker heartbeat received."""
    status: str
    progress: float | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerFailedEvent(AutonomousEvent):
    """Worker has failed."""
    failure: str
    crash_detected: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerCancelledEvent(AutonomousEvent):
    """Worker has been cancelled."""
    reason: str | None = None


# ========================================================================
# Checkpoint Events
# ========================================================================

@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointCreatedEvent(AutonomousEvent):
    """Checkpoint has been created."""
    checkpoint_id: str
    version: int
    state_size_bytes: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointRestoredEvent(AutonomousEvent):
    """Checkpoint has been restored for recovery."""
    checkpoint_id: str
    version: int


# ========================================================================
# Recovery Events
# ========================================================================

@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryStartedEvent(AutonomousEvent):
    """Recovery process has started."""
    recovery_action: str
    target_status: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryCompletedEvent(AutonomousEvent):
    """Recovery process has completed successfully."""
    recovery_action: str
    restored_checkpoint_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryFailedEvent(AutonomousEvent):
    """Recovery process has failed."""
    failure: str
    recovery_action: str