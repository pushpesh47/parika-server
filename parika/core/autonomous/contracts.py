"""
PARIKA Autonomous Execution Contracts

Defines the architectural contracts for autonomous execution:
- State machines for missions, tasks, agents, workers, executions
- Contracts defining the expected behavior and invariants
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class MissionStatus(StrEnum):
    """
    Mission lifecycle states.
    
    State machine:
        CREATED -> PLANNING -> RUNNING
                          -> RUNNING -> WAITING -> RUNNING
                          -> RUNNING -> PAUSED -> RUNNING
                          -> RUNNING -> BLOCKED -> RUNNING
                          -> RUNNING -> NEEDS_APPROVAL -> RUNNING
                          -> RUNNING -> FAILED
                          -> RUNNING -> CANCELLED
                          -> RUNNING -> COMPLETED
        Any state -> FAILED (on error)
        Any state -> CANCELLED (on user request)
    """
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    BLOCKED = "blocked"
    NEEDS_APPROVAL = "needs_approval"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class AutonomousTaskStatus(StrEnum):
    """
    Autonomous task lifecycle states.
    
    State machine:
        CREATED -> SCHEDULED -> RUNNING
                        -> RUNNING -> WAITING_FOR_DEPENDENCY -> READY -> RUNNING
                        -> RUNNING -> WAITING_FOR_RESOURCE -> READY -> RUNNING
                        -> RUNNING -> WAITING_FOR_APPROVAL -> READY -> RUNNING
                        -> RUNNING -> PAUSED -> RUNNING
                        -> RUNNING -> BLOCKED -> RUNNING
                        -> RUNNING -> COMPLETED
                        -> RUNNING -> FAILED -> RETRYING -> RUNNING (if retries remain)
                        -> RUNNING -> FAILED (if no retries or max retries reached)
                        -> RUNNING -> CANCELLED
        RECOVERING -> RUNNING (after checkpoint restore)
    """
    CREATED = "created"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    WAITING_FOR_DEPENDENCY = "waiting_for_dependency"
    WAITING_FOR_RESOURCE = "waiting_for_resource"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    READY = "ready"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    RECOVERING = "recovering"


class AgentInstanceStatus(StrEnum):
    """
    Agent instance lifecycle states.
    
    State machine:
        SPAWNED -> STARTING -> RUNNING
                        -> RUNNING -> WAITING -> RUNNING
                        -> RUNNING -> PAUSED -> RUNNING
                        -> RUNNING -> COMPLETED
                        -> RUNNING -> FAILED
                        -> RUNNING -> TERMINATED
    """
    SPAWNED = "spawned"
    STARTING = "starting"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class WorkerStatus(StrEnum):
    """
    Worker lifecycle states.
    
    State machine:
        SPAWNED -> STARTING -> RUNNING
                        -> RUNNING -> HEARTBEAT (periodic)
                        -> RUNNING -> PAUSING -> PAUSED
                        -> PAUSED -> RESUMING -> RUNNING
                        -> RUNNING -> CANCELLING -> CANCELLED
                        -> RUNNING -> COMPLETING -> COMPLETED
                        -> RUNNING -> FAILING -> FAILED
                        -> RUNNING -> CRASHED (detected via heartbeat timeout)
        CRASHED -> RECOVERING -> RUNNING (if recovery succeeds)
        CRASHED -> FAILED (if recovery fails)
    """
    SPAWNED = "spawned"
    STARTING = "starting"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETING = "completing"
    COMPLETED = "completed"
    FAILING = "failing"
    FAILED = "failed"
    CRASHED = "crashed"
    RECOVERING = "recovering"


class ExecutionStatus(StrEnum):
    """
    Execution attempt states.
    
    Each autonomous task can have multiple execution attempts.
    State machine:
        CREATED -> STARTED -> RUNNING
                        -> RUNNING -> CHECKPOINTING -> RUNNING
                        -> RUNNING -> COMPLETED
                        -> RUNNING -> FAILED
                        -> RUNNING -> CANCELLED
                        -> RUNNING -> TIMED_OUT
    """
    CREATED = "created"
    STARTED = "started"
    RUNNING = "running"
    CHECKPOINTING = "checkpointing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class CheckpointStatus(StrEnum):
    """
    Checkpoint states.
    
    State machine:
        CREATING -> VALID -> AVAILABLE
                    -> INVALID (validation failed)
        AVAILABLE -> RESTORING -> RESTORED
        AVAILABLE -> INVALIDATED (superseded or corrupted)
    """
    CREATING = "creating"
    VALID = "valid"
    AVAILABLE = "available"
    INVALID = "invalid"
    RESTORING = "restoring"
    RESTORED = "restored"
    INVALIDATED = "invalidated"


class RecoveryAction(StrEnum):
    """
    Recovery actions for unfinished work.
    """
    RESUME = "resume"
    RESTART_FROM_CHECKPOINT = "restart_from_checkpoint"
    RETRY = "retry"
    CANCEL = "cancel"
    MARK_FAILED = "mark_failed"
    NO_ACTION = "no_action"


class DependencyStatus(StrEnum):
    """
    Task dependency states.
    """
    WAITING = "waiting"
    SATISFIED = "satisfied"
    FAILED = "failed"
    CANCELLED = "cancelled"


# -------------------------------------------------------------------------
# Contracts - Define the expected structure and invariants
# -------------------------------------------------------------------------

@dataclass(frozen=True, slots=True, kw_only=True)
class MissionContract:
    """
    Contract defining the Mission abstraction.
    
    A Mission represents a long-running objective that may contain
    multiple tasks and agents.
    """
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
    
    def __post_init__(self) -> None:
        if not 0 <= self.progress <= 1:
            raise ValueError("progress must be between 0 and 1")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class AutonomousTaskContract:
    """
    Contract defining the AutonomousTask abstraction.
    
    An autonomous task represents a unit of work that can execute
    independently of an active user request.
    """
    id: str
    mission_id: str
    parent_task_id: str | None
    agent_id: str | None
    name: str
    description: str
    capability_id: str | None
    inputs: MappingProxyType[str, Any]
    status: AutonomousTaskStatus
    priority: int
    progress: float
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    deadline: datetime | None
    max_retries: int
    retry_count: int
    resource_budget: MappingProxyType[str, Any]
    checkpoint_id: str | None
    result: MappingProxyType[str, Any] | None
    failure: str | None
    metadata: MappingProxyType[str, Any]
    provider_request_type: str | None
    task_category: str | None
    execution_requirements: MappingProxyType[str, Any] | None
    
    def __post_init__(self) -> None:
        if not 0 <= self.progress <= 1:
            raise ValueError("progress must be between 0 and 1")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_count < 0:
            raise ValueError("retry_count must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentInstanceContract:
    """
    Contract defining the AgentInstance abstraction.
    
    An agent instance represents a concrete agent executing a task
    with its own identity, context, and lifecycle.
    """
    id: str
    mission_id: str
    task_id: str
    agent_profile_id: str
    parent_agent_id: str | None
    child_agent_ids: tuple[str, ...]
    status: AgentInstanceStatus
    runtime: str
    permission_context: MappingProxyType[str, Any]
    resource_budget: MappingProxyType[str, Any]
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    last_heartbeat: datetime | None
    result: MappingProxyType[str, Any] | None
    failure: str | None
    metadata: MappingProxyType[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerContract:
    """
    Contract defining the Worker abstraction.
    
    A worker executes autonomous tasks independently. The abstraction
    supports future process/runtime isolation.
    """
    id: str
    task_id: str
    execution_id: str
    status: WorkerStatus
    started_at: datetime
    last_activity: datetime
    last_heartbeat: datetime | None
    heartbeat_interval_seconds: float
    timeout_seconds: float
    result: MappingProxyType[str, Any] | None
    error: str | None
    metadata: MappingProxyType[str, Any]
    
    def __post_init__(self) -> None:
        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionContract:
    """
    Contract defining an Execution attempt.
    
    Each task execution attempt is tracked separately for idempotency
    and recovery purposes.
    """
    id: str
    task_id: str
    worker_id: str
    status: ExecutionStatus
    attempt_number: int
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    checkpoint_id: str | None
    result: MappingProxyType[str, Any] | None
    error: str | None
    metadata: MappingProxyType[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckpointContract:
    """
    Contract defining a Checkpoint.
    
    A checkpoint represents enough execution state to safely recover
    an autonomous task. Must be deterministic, versioned, validated,
    persistent, and recoverable.
    """
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
    
    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("checkpoint version must be >= 1")


@dataclass(frozen=True, slots=True, kw_only=True)
class WorldStateContract:
    """
    Contract defining the global autonomous activity state.
    
    Represents operational state reconstructable from authoritative
    persistent state. Not a memory system - operational state only.
    """
    active_missions: int
    active_tasks: int
    active_agents: int
    waiting_tasks: int
    blocked_tasks: int
    failed_tasks: int
    retrying_tasks: int
    scheduled_tasks: int
    pending_approvals: int
    active_workers: int
    crashed_workers: int
    resource_usage: MappingProxyType[str, Any]
    last_updated: datetime


# -------------------------------------------------------------------------
# Validation Functions
# -------------------------------------------------------------------------

def validate_mission_transition(from_status: MissionStatus, to_status: MissionStatus) -> bool:
    """
    Validate a mission state transition.
    
    Returns True if the transition is valid, False otherwise.
    """
    valid_transitions = {
        MissionStatus.CREATED: {MissionStatus.PLANNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.PLANNING: {MissionStatus.RUNNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.RUNNING: {
            MissionStatus.WAITING, MissionStatus.PAUSED, MissionStatus.BLOCKED,
            MissionStatus.NEEDS_APPROVAL, MissionStatus.COMPLETED, MissionStatus.FAILED,
            MissionStatus.CANCELLED
        },
        MissionStatus.WAITING: {MissionStatus.RUNNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.PAUSED: {MissionStatus.RUNNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.BLOCKED: {MissionStatus.RUNNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.NEEDS_APPROVAL: {MissionStatus.RUNNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.FAILED: set(),  # Terminal
        MissionStatus.CANCELLED: set(),  # Terminal
        MissionStatus.COMPLETED: set(),  # Terminal
    }
    return to_status in valid_transitions.get(from_status, set())


def validate_task_transition(from_status: AutonomousTaskStatus, to_status: AutonomousTaskStatus) -> bool:
    """
    Validate an autonomous task state transition.
    """
    valid_transitions = {
        AutonomousTaskStatus.CREATED: {AutonomousTaskStatus.SCHEDULED, AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.FAILED},
        AutonomousTaskStatus.SCHEDULED: {AutonomousTaskStatus.RUNNING, AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.FAILED},
        AutonomousTaskStatus.RUNNING: {
            AutonomousTaskStatus.WAITING_FOR_DEPENDENCY,
            AutonomousTaskStatus.WAITING_FOR_RESOURCE,
            AutonomousTaskStatus.WAITING_FOR_APPROVAL,
            AutonomousTaskStatus.PAUSED,
            AutonomousTaskStatus.BLOCKED,
            AutonomousTaskStatus.COMPLETED,
            AutonomousTaskStatus.FAILED,
            AutonomousTaskStatus.CANCELLED,
        },
        AutonomousTaskStatus.WAITING_FOR_DEPENDENCY: {AutonomousTaskStatus.READY, AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.FAILED},
        AutonomousTaskStatus.WAITING_FOR_RESOURCE: {AutonomousTaskStatus.READY, AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.FAILED},
        AutonomousTaskStatus.WAITING_FOR_APPROVAL: {AutonomousTaskStatus.READY, AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.FAILED},
        AutonomousTaskStatus.READY: {AutonomousTaskStatus.RUNNING, AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.FAILED},
        AutonomousTaskStatus.PAUSED: {AutonomousTaskStatus.RUNNING, AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.FAILED},
        AutonomousTaskStatus.BLOCKED: {AutonomousTaskStatus.RUNNING, AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.FAILED},
        AutonomousTaskStatus.FAILED: {AutonomousTaskStatus.RETRYING, AutonomousTaskStatus.CANCELLED},
        AutonomousTaskStatus.RETRYING: {AutonomousTaskStatus.RUNNING, AutonomousTaskStatus.FAILED, AutonomousTaskStatus.CANCELLED},
        AutonomousTaskStatus.CANCELLED: set(),  # Terminal
        AutonomousTaskStatus.COMPLETED: set(),  # Terminal
        AutonomousTaskStatus.RECOVERING: {AutonomousTaskStatus.RUNNING, AutonomousTaskStatus.FAILED, AutonomousTaskStatus.CANCELLED},
    }
    return to_status in valid_transitions.get(from_status, set())


def validate_worker_transition(from_status: WorkerStatus, to_status: WorkerStatus) -> bool:
    """
    Validate a worker state transition.
    """
    valid_transitions = {
        WorkerStatus.SPAWNED: {WorkerStatus.STARTING, WorkerStatus.CANCELLED, WorkerStatus.FAILED},
        WorkerStatus.STARTING: {WorkerStatus.RUNNING, WorkerStatus.FAILED, WorkerStatus.CANCELLED},
        WorkerStatus.RUNNING: {
            WorkerStatus.PAUSING, WorkerStatus.CANCELLING, WorkerStatus.COMPLETING,
            WorkerStatus.FAILING, WorkerStatus.CRASHED
        },
        WorkerStatus.PAUSING: {WorkerStatus.PAUSED, WorkerStatus.FAILED},
        WorkerStatus.PAUSED: {WorkerStatus.RESUMING, WorkerStatus.CANCELLING, WorkerStatus.FAILED},
        WorkerStatus.RESUMING: {WorkerStatus.RUNNING, WorkerStatus.FAILED},
        WorkerStatus.CANCELLING: {WorkerStatus.CANCELLED, WorkerStatus.FAILED},
        WorkerStatus.COMPLETING: {WorkerStatus.COMPLETED, WorkerStatus.FAILED},
        WorkerStatus.FAILING: {WorkerStatus.FAILED},
        WorkerStatus.CRASHED: {WorkerStatus.RECOVERING, WorkerStatus.FAILED},
        WorkerStatus.RECOVERING: {WorkerStatus.RUNNING, WorkerStatus.FAILED},
        WorkerStatus.CANCELLED: set(),
        WorkerStatus.COMPLETED: set(),
        WorkerStatus.FAILED: set(),
    }
    return to_status in valid_transitions.get(from_status, set())


def validate_execution_transition(from_status: ExecutionStatus, to_status: ExecutionStatus) -> bool:
    """
    Validate an execution state transition.
    """
    valid_transitions = {
        ExecutionStatus.CREATED: {ExecutionStatus.STARTED, ExecutionStatus.CANCELLED, ExecutionStatus.FAILED},
        ExecutionStatus.STARTED: {ExecutionStatus.RUNNING, ExecutionStatus.CANCELLED, ExecutionStatus.FAILED},
        ExecutionStatus.RUNNING: {
            ExecutionStatus.CHECKPOINTING,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
        },
        ExecutionStatus.CHECKPOINTING: {ExecutionStatus.RUNNING, ExecutionStatus.FAILED},
        ExecutionStatus.COMPLETED: set(),
        ExecutionStatus.FAILED: set(),
        ExecutionStatus.CANCELLED: set(),
        ExecutionStatus.TIMED_OUT: set(),
    }
    return to_status in valid_transitions.get(from_status, set())


def validate_checkpoint_transition(from_status: CheckpointStatus, to_status: CheckpointStatus) -> bool:
    """
    Validate a checkpoint state transition.
    """
    valid_transitions = {
        CheckpointStatus.CREATING: {CheckpointStatus.VALID, CheckpointStatus.INVALID},
        CheckpointStatus.VALID: {CheckpointStatus.AVAILABLE, CheckpointStatus.INVALID},
        CheckpointStatus.AVAILABLE: {CheckpointStatus.RESTORING, CheckpointStatus.INVALIDATED},
        CheckpointStatus.RESTORING: {CheckpointStatus.RESTORED, CheckpointStatus.INVALID},
        CheckpointStatus.RESTORED: {CheckpointStatus.INVALIDATED},
        CheckpointStatus.INVALID: set(),
        CheckpointStatus.INVALIDATED: set(),
    }
    return to_status in valid_transitions.get(from_status, set())