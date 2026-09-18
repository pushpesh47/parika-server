"""
PARIKA Autonomous Execution Models

SQLAlchemy models for persistent autonomous execution state.
These models map to PostgreSQL tables via Alembic migrations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from parika.core.autonomous.contracts import (
    MissionStatus,
    AutonomousTaskStatus,
    AgentInstanceStatus,
    WorkerStatus,
    ExecutionStatus,
    CheckpointStatus,
    DependencyStatus,
)


class Base(DeclarativeBase):
    """Base class for autonomous execution models."""
    pass


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


def generate_uuid() -> str:
    """Generate a UUID string."""
    return uuid4().hex


# ========================================================================
# Mission Model
# ========================================================================

class MissionModel(Base):
    """Persistent Mission model."""
    __tablename__ = "mission"
    __table_args__ = (
        Index("ix_mission_status", "status"),
        Index("ix_mission_created_at", "created_at"),
        Index("ix_mission_updated_at", "updated_at"),
        {"schema": "execution"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MissionStatus.CREATED.value)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mission_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    failure: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    tasks: Mapped[list["AutonomousTaskModel"]] = relationship("AutonomousTaskModel", back_populates="mission", cascade="all, delete-orphan")
    agents: Mapped[list["AgentInstanceModel"]] = relationship("AgentInstanceModel", back_populates="mission", cascade="all, delete-orphan")
    checkpoints: Mapped[list["CheckpointModel"]] = relationship("CheckpointModel", back_populates="mission", cascade="all, delete-orphan")


# ========================================================================
# Autonomous Task Model
# ========================================================================

class AutonomousTaskModel(Base):
    """Persistent Autonomous Task model."""
    __tablename__ = "autonomous_task"
    __table_args__ = (
        Index("ix_autonomous_task_mission_id", "mission_id"),
        Index("ix_autonomous_task_status", "status"),
        Index("ix_autonomous_task_parent_task_id", "parent_task_id"),
        Index("ix_autonomous_task_agent_id", "agent_id"),
        Index("ix_autonomous_task_created_at", "created_at"),
        Index("ix_autonomous_task_updated_at", "updated_at"),
        Index("ix_autonomous_task_deadline", "deadline"),
        Index("ix_autonomous_task_provider_request_type", "provider_request_type"),
        Index("ix_autonomous_task_task_category", "task_category"),
        {"schema": "execution"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    mission_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.mission.id", ondelete="CASCADE"), nullable=False)
    parent_task_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("execution.autonomous_task.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("execution.agent_instance.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    capability_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AutonomousTaskStatus.CREATED.value)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resource_budget: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    checkpoint_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("execution.checkpoint.id", ondelete="SET NULL"), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    failure: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    provider_request_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    execution_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    mission: Mapped["MissionModel"] = relationship("MissionModel", back_populates="tasks")
    parent_task: Mapped["AutonomousTaskModel | None"] = relationship("AutonomousTaskModel", remote_side=[id], back_populates="child_tasks")
    child_tasks: Mapped[list["AutonomousTaskModel"]] = relationship("AutonomousTaskModel", back_populates="parent_task")
    agent: Mapped["AgentInstanceModel | None"] = relationship("AgentInstanceModel", foreign_keys="AgentInstanceModel.task_id", back_populates="task")
    dependencies: Mapped[list["TaskDependencyModel"]] = relationship("TaskDependencyModel", foreign_keys="TaskDependencyModel.task_id", back_populates="task", cascade="all, delete-orphan")
    dependents: Mapped[list["TaskDependencyModel"]] = relationship("TaskDependencyModel", foreign_keys="TaskDependencyModel.depends_on_task_id", back_populates="depends_on_task")
    executions: Mapped[list["ExecutionModel"]] = relationship("ExecutionModel", foreign_keys="ExecutionModel.task_id", back_populates="task", cascade="all, delete-orphan")
    checkpoint: Mapped["CheckpointModel | None"] = relationship("CheckpointModel", foreign_keys="CheckpointModel.task_id", back_populates="task")


# ========================================================================
# Task Dependency Model
# ========================================================================

class TaskDependencyModel(Base):
    """Persistent Task Dependency model."""
    __tablename__ = "task_dependency"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
        Index("ix_task_dependency_task_id", "task_id"),
        Index("ix_task_dependency_depends_on_task_id", "depends_on_task_id"),
        Index("ix_task_dependency_status", "status"),
        {"schema": "execution"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False)
    depends_on_task_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DependencyStatus.WAITING.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    satisfied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    task: Mapped["AutonomousTaskModel"] = relationship("AutonomousTaskModel", foreign_keys=[task_id], back_populates="dependencies")
    depends_on_task: Mapped["AutonomousTaskModel"] = relationship("AutonomousTaskModel", foreign_keys=[depends_on_task_id], back_populates="dependents")


# ========================================================================
# Agent Instance Model
# ========================================================================

class AgentInstanceModel(Base):
    """Persistent Agent Instance model."""
    __tablename__ = "agent_instance"
    __table_args__ = (
        Index("ix_agent_instance_mission_id", "mission_id"),
        Index("ix_agent_instance_task_id", "task_id"),
        Index("ix_agent_instance_parent_agent_id", "parent_agent_id"),
        Index("ix_agent_instance_status", "status"),
        Index("ix_agent_instance_last_heartbeat", "last_heartbeat"),
        {"schema": "execution"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    mission_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.mission.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False)
    agent_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_agent_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("execution.agent_instance.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentInstanceStatus.SPAWNED.value)
    runtime: Mapped[str] = mapped_column(String(64), nullable=False, default="native")  # Kept for DB compatibility
    permission_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    resource_budget: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    failure: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # Relationships
    mission: Mapped["MissionModel"] = relationship("MissionModel", back_populates="agents")
    task: Mapped["AutonomousTaskModel"] = relationship("AutonomousTaskModel", foreign_keys="AgentInstanceModel.task_id", back_populates="agent")
    parent_agent: Mapped["AgentInstanceModel | None"] = relationship("AgentInstanceModel", remote_side=[id], back_populates="child_agents")
    child_agents: Mapped[list["AgentInstanceModel"]] = relationship("AgentInstanceModel", back_populates="parent_agent")


# ========================================================================
# Worker Model
# ========================================================================

class WorkerModel(Base):
    """Persistent Worker model."""
    __tablename__ = "worker"
    __table_args__ = (
        Index("ix_worker_task_id", "task_id"),
        Index("ix_worker_execution_id", "execution_id"),
        Index("ix_worker_status", "status"),
        Index("ix_worker_last_heartbeat", "last_heartbeat"),
        {"schema": "execution"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.execution.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkerStatus.SPAWNED.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_activity: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_interval_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=120.0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # Relationships
    task: Mapped["AutonomousTaskModel"] = relationship("AutonomousTaskModel")
    execution: Mapped["ExecutionModel"] = relationship("ExecutionModel", foreign_keys="WorkerModel.execution_id")


# ========================================================================
# Execution Model
# ========================================================================

class ExecutionModel(Base):
    """Persistent Execution Attempt model."""
    __tablename__ = "execution"
    __table_args__ = (
        Index("ix_execution_task_id", "task_id"),
        Index("ix_execution_worker_id", "worker_id"),
        Index("ix_execution_status", "status"),
        Index("ix_execution_started_at", "started_at"),
        Index("ix_execution_implementation_id", "selected_implementation_id"),
        Index("ix_execution_agent_id", "agent_id"),
        {"schema": "execution"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("execution.worker.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ExecutionStatus.CREATED.value)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("execution.checkpoint.id", ondelete="SET NULL"), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # New audit fields
    selected_implementation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    implementation_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    implementation_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_backend: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required_environment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actual_environment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_decision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    budget_allocation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fallback_from_execution_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("execution.execution.id", ondelete="SET NULL"), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    task: Mapped["AutonomousTaskModel"] = relationship("AutonomousTaskModel", back_populates="executions")
    worker: Mapped["WorkerModel"] = relationship("WorkerModel", foreign_keys="ExecutionModel.worker_id", remote_side="WorkerModel.id", uselist=False)
    checkpoint: Mapped["CheckpointModel | None"] = relationship("CheckpointModel", foreign_keys="ExecutionModel.checkpoint_id")
    fallback_from: Mapped["ExecutionModel | None"] = relationship("ExecutionModel", remote_side=[id], back_populates="fallback_executions", foreign_keys="ExecutionModel.fallback_from_execution_id")
    fallback_executions: Mapped[list["ExecutionModel"]] = relationship("ExecutionModel", back_populates="fallback_from", foreign_keys="ExecutionModel.fallback_from_execution_id")


# ========================================================================
# Checkpoint Model
# ========================================================================

class CheckpointModel(Base):
    """Persistent Checkpoint model."""
    __tablename__ = "checkpoint"
    __table_args__ = (
        Index("ix_checkpoint_task_id", "task_id"),
        Index("ix_checkpoint_execution_id", "execution_id"),
        Index("ix_checkpoint_mission_id", "mission_id"),
        Index("ix_checkpoint_agent_id", "agent_id"),
        Index("ix_checkpoint_status", "status"),
        Index("ix_checkpoint_created_at", "created_at"),
        {"schema": "execution"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.execution.id", ondelete="CASCADE"), nullable=False)
    mission_id: Mapped[str] = mapped_column(String(64), ForeignKey("execution.mission.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("execution.agent_instance.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=CheckpointStatus.CREATING.value)
    state_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # Relationships
    task: Mapped["AutonomousTaskModel"] = relationship("AutonomousTaskModel", foreign_keys="CheckpointModel.task_id", back_populates="checkpoint")
    execution: Mapped["ExecutionModel"] = relationship("ExecutionModel", foreign_keys="CheckpointModel.execution_id", remote_side="ExecutionModel.id", viewonly=True)
    mission: Mapped["MissionModel"] = relationship("MissionModel", back_populates="checkpoints")


# ========================================================================
# World State Model (for operational state snapshot)
# ========================================================================

class WorldStateModel(Base):
    """Persistent World State snapshot model."""
    __tablename__ = "world_state"
    __table_args__ = (
        Index("ix_world_state_updated_at", "updated_at"),
        {"schema": "execution"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    active_missions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_agents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waiting_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrying_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_approvals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_workers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crashed_workers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resource_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


# ========================================================================
# Event Persistence Model (for autonomous event audit trail)
# ========================================================================

class AutonomousEventModel(Base):
    """Persistent Autonomous Event model for audit/recovery."""
    __tablename__ = "autonomous_event"
    __table_args__ = (
        Index("ix_autonomous_event_mission_id", "mission_id"),
        Index("ix_autonomous_event_task_id", "task_id"),
        Index("ix_autonomous_event_agent_id", "agent_id"),
        Index("ix_autonomous_event_execution_id", "execution_id"),
        Index("ix_autonomous_event_worker_id", "worker_id"),
        Index("ix_autonomous_event_event_type", "event_type"),
        Index("ix_autonomous_event_timestamp", "timestamp"),
        {"schema": "execution"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    
    # Correlation IDs
    mission_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    
    # Event payload
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


# ========================================================================
# Agent Message Model (for inter-agent communication)
# ========================================================================

class AgentMessageModel(Base):
    """Persistent Agent Message model for A2A communication."""
    __tablename__ = "agent_message"
    __table_args__ = (
        Index("ix_agent_message_mission_id", "mission_id"),
        Index("ix_agent_message_sender_id", "sender_agent_id"),
        Index("ix_agent_message_recipient_id", "recipient_agent_id"),
        Index("ix_agent_message_status", "status"),
        Index("ix_agent_message_timestamp", "timestamp"),
        {"schema": "execution"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    
    # Correlation IDs
    mission_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sender_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    
    # Message content
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending, delivered, read, failed
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")