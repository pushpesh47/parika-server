"""
PARIKA Agent Message Models

Defines the durable message structure for agent-to-agent communication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class MessageType(StrEnum):
    """Types of agent messages."""
    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    TASK_DELEGATION = "task_delegation"
    TASK_RESULT = "task_result"
    STATUS_UPDATE = "status_update"
    HEARTBEAT = "heartbeat"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"
    DATA_SHARE = "data_share"
    QUERY = "query"
    QUERY_RESPONSE = "query_response"
    EVENT_NOTIFICATION = "event_notification"
    ERROR = "error"
    CUSTOM = "custom"


class MessageStatus(StrEnum):
    """Message delivery status."""
    SENT = "sent"
    DELIVERED = "delivered"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class MessagePriority(StrEnum):
    """Message priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentMessage:
    """
    Durable agent-to-agent message.

    All messages are persisted for recovery and audit.
    """
    id: str
    message_id: str
    sender_agent_id: str
    recipient_agent_id: str | None  # None for broadcast
    mission_id: str
    task_id: str | None
    correlation_id: str | None
    message_type: MessageType
    priority: MessagePriority
    payload: MappingProxyType[str, Any]
    status: MessageStatus
    created_at: datetime
    delivered_at: datetime | None = None
    processed_at: datetime | None = None
    expires_at: datetime | None = None
    retry_count: int = 0
    max_retries: int = 3
    error: str | None = None
    metadata: MappingProxyType[str, Any] = MappingProxyType({})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "sender_agent_id": self.sender_agent_id,
            "recipient_agent_id": self.recipient_agent_id,
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "message_type": self.message_type.value,
            "priority": self.priority.value,
            "payload": dict(self.payload),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def create(
        cls,
        sender_agent_id: str,
        recipient_agent_id: str | None,
        mission_id: str,
        message_type: MessageType,
        payload: MappingProxyType[str, Any],
        *,
        task_id: str | None = None,
        correlation_id: str | None = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        expires_at: datetime | None = None,
        max_retries: int = 3,
        metadata: MappingProxyType[str, Any] | None = None,
    ) -> "AgentMessage":
        """Create a new agent message."""
        now = datetime.now(UTC)
        return cls(
            id=f"msg_{uuid4().hex[:16]}",
            message_id=f"msg_{uuid4().hex[:16]}",
            sender_agent_id=sender_agent_id,
            recipient_agent_id=recipient_agent_id,
            mission_id=mission_id,
            task_id=task_id,
            correlation_id=correlation_id,
            message_type=message_type,
            priority=priority,
            payload=payload,
            status=MessageStatus.SENT,
            created_at=now,
            expires_at=expires_at,
            max_retries=max_retries,
            metadata=metadata or MappingProxyType({}),
        )

    def with_status(self, status: MessageStatus, error: str | None = None) -> "AgentMessage":
        """Return message with updated status."""
        now = datetime.now(UTC)
        delivered = self.delivered_at
        processed = self.processed_at

        if status == MessageStatus.DELIVERED and not delivered:
            delivered = now
        if status == MessageStatus.PROCESSED and not processed:
            processed = now

        return AgentMessage(
            id=self.id,
            message_id=self.message_id,
            sender_agent_id=self.sender_agent_id,
            recipient_agent_id=self.recipient_agent_id,
            mission_id=self.mission_id,
            task_id=self.task_id,
            correlation_id=self.correlation_id,
            message_type=self.message_type,
            priority=self.priority,
            payload=self.payload,
            status=status,
            created_at=self.created_at,
            delivered_at=delivered,
            processed_at=processed,
            expires_at=self.expires_at,
            retry_count=self.retry_count,
            max_retries=self.max_retries,
            error=error,
            metadata=self.metadata,
        )

    def with_retry(self) -> "AgentMessage":
        """Return message with incremented retry count."""
        return AgentMessage(
            id=self.id,
            message_id=self.message_id,
            sender_agent_id=self.sender_agent_id,
            recipient_agent_id=self.recipient_agent_id,
            mission_id=self.mission_id,
            task_id=self.task_id,
            correlation_id=self.correlation_id,
            message_type=self.message_type,
            priority=self.priority,
            payload=self.payload,
            status=MessageStatus.SENT,
            created_at=self.created_at,
            delivered_at=None,
            processed_at=None,
            expires_at=self.expires_at,
            retry_count=self.retry_count + 1,
            max_retries=self.max_retries,
            error=self.error,
            metadata=self.metadata,
        )

    def is_expired(self) -> bool:
        """Check if message has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def can_retry(self) -> bool:
        """Check if message can be retried."""
        return self.retry_count < self.max_retries and self.status in (
            MessageStatus.FAILED, MessageStatus.SENT
        )


def generate_message_id() -> str:
    """Generate a unique message ID."""
    return f"msg_{uuid4().hex[:16]}"