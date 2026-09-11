"""
PARIKA Wait Condition Models

Defines durable wait conditions for autonomous tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class WaitConditionType(StrEnum):
    """Types of wait conditions."""
    DEPENDENCY = "dependency"           # Wait for task dependency
    RESOURCE = "resource"               # Wait for resource availability
    APPROVAL = "approval"               # Wait for user approval
    AGENT_MESSAGE = "agent_message"     # Wait for agent message
    EXTERNAL_EVENT = "external_event"   # Wait for external event
    FILE_EXISTS = "file_exists"         # Wait for file to exist
    HTTP_RESPONSE = "http_response"     # Wait for HTTP response
    TIME = "time"                       # Wait until specific time
    CUSTOM = "custom"                   # Custom condition


class WaitConditionStatus(StrEnum):
    """Wait condition status."""
    PENDING = "pending"
    WAITING = "waiting"
    SATISFIED = "satisfied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class WaitCondition:
    """
    Durable wait condition for autonomous tasks.

    Tasks can enter a waiting state with a condition that will be
    evaluated by the WaitManager when relevant events occur.
    """
    id: str
    task_id: str
    mission_id: str
    condition_type: WaitConditionType
    condition_data: MappingProxyType[str, Any]
    status: WaitConditionStatus
    created_at: datetime
    started_at: datetime | None = None
    satisfied_at: datetime | None = None
    expires_at: datetime | None = None
    error: str | None = None
    metadata: MappingProxyType[str, Any] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "mission_id": self.mission_id,
            "condition_type": self.condition_type.value,
            "condition_data": dict(self.condition_data),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "satisfied_at": self.satisfied_at.isoformat() if self.satisfied_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def create(
        cls,
        task_id: str,
        mission_id: str,
        condition_type: WaitConditionType,
        condition_data: MappingProxyType[str, Any],
        *,
        expires_at: datetime | None = None,
        metadata: MappingProxyType[str, Any] | None = None,
    ) -> "WaitCondition":
        """Create a new wait condition."""
        now = datetime.now(UTC)
        return cls(
            id=f"wait_{uuid4().hex[:16]}",
            task_id=task_id,
            mission_id=mission_id,
            condition_type=condition_type,
            condition_data=condition_data,
            status=WaitConditionStatus.PENDING,
            created_at=now,
            expires_at=expires_at,
            metadata=metadata or MappingProxyType({}),
        )

    def with_status(
        self,
        status: WaitConditionStatus,
        error: str | None = None,
    ) -> "WaitCondition":
        """Return wait condition with updated status."""
        now = datetime.now(UTC)
        started = self.started_at
        satisfied = self.satisfied_at

        if status == WaitConditionStatus.WAITING and not started:
            started = now
        if status == WaitConditionStatus.SATISFIED and not satisfied:
            satisfied = now

        return WaitCondition(
            id=self.id,
            task_id=self.task_id,
            mission_id=self.mission_id,
            condition_type=self.condition_type,
            condition_data=self.condition_data,
            status=status,
            created_at=self.created_at,
            started_at=started,
            satisfied_at=satisfied,
            expires_at=self.expires_at,
            error=error,
            metadata=self.metadata,
        )

    def is_expired(self) -> bool:
        """Check if wait condition has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at


# Pre-defined condition data structures

@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyWaitData:
    """Wait for task dependencies."""
    depends_on_task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ResourceWaitData:
    """Wait for resource availability."""
    resource_type: str  # "cpu", "memory", "gpu", "custom"
    required_amount: float
    resource_constraints: MappingProxyType[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalWaitData:
    """Wait for user approval."""
    approval_id: str
    requested_operation: str
    context: MappingProxyType[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentMessageWaitData:
    """Wait for agent message."""
    expected_message_type: str
    from_agent_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalEventWaitData:
    """Wait for external event."""
    event_source: str
    event_type: str
    event_filter: MappingProxyType[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class FileWaitData:
    """Wait for file to exist."""
    file_path: str
    check_interval_seconds: float = 5.0


@dataclass(frozen=True, slots=True, kw_only=True)
class TimeWaitData:
    """Wait until specific time."""
    wake_at: datetime
    timezone: str = "UTC"


def generate_wait_id() -> str:
    """Generate a unique wait condition ID."""
    return f"wait_{uuid4().hex[:16]}"