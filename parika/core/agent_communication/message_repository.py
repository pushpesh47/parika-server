"""
PARIKA Agent Message Repository

Provides persistence for agent messages.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

from parika.core.autonomous.repository import (
    MissionRepository,
    AutonomousTaskRepository,
    AgentInstanceRepository,
)
from parika.core.agent_communication.message import (
    AgentMessage,
    MessageStatus,
    MessagePriority,
)
from parika.core.database.pool import PoolManager
from parika.core.logger.logger import Logger


class AgentMessageRepository:
    """
    Repository for persisting agent messages.

    Uses the execution schema for message storage.
    """

    def __init__(
        self,
        pool_manager: PoolManager,
        logger: Logger,
    ) -> None:
        self._pool_manager = pool_manager
        self._logger = logger.get_logger(__name__)
        self._lock = threading.RLock()

        # In-memory cache for recent messages (for fast lookups)
        self._cache: dict[str, AgentMessage] = {}
        self._cache_limit = 1000

    def create(self, message: AgentMessage) -> AgentMessage:
        """Persist a new message."""
        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.agent_message (
                        id, message_id, sender_agent_id, recipient_agent_id,
                        mission_id, task_id, correlation_id, message_type,
                        priority, payload, status, created_at, delivered_at,
                        processed_at, expires_at, retry_count, max_retries,
                        error, metadata
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        message.id,
                        message.message_id,
                        message.sender_agent_id,
                        message.recipient_agent_id,
                        message.mission_id,
                        message.task_id,
                        message.correlation_id,
                        message.message_type.value,
                        message.priority.value,
                        json.dumps(dict(message.payload)),
                        message.status.value,
                        message.created_at,
                        message.delivered_at,
                        message.processed_at,
                        message.expires_at,
                        message.retry_count,
                        message.max_retries,
                        message.error,
                        json.dumps(dict(message.metadata)),
                    ),
                )
                conn.commit()

        # Add to cache
        with self._lock:
            self._cache[message.id] = message
            if len(self._cache) > self._cache_limit:
                # Remove oldest
                oldest = min(self._cache.values(), key=lambda m: m.created_at)
                self._cache.pop(oldest.id, None)

        self._logger.debug("Persisted agent message '%s'", message.id)
        return message

    def get(self, message_id: str) -> AgentMessage | None:
        """Get a message by ID."""
        # Check cache first
        with self._lock:
            if message_id in self._cache:
                return self._cache[message_id]

        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, message_id, sender_agent_id, recipient_agent_id,
                           mission_id, task_id, correlation_id, message_type,
                           priority, payload, status, created_at, delivered_at,
                           processed_at, expires_at, retry_count, max_retries,
                           error, metadata
                    FROM execution.agent_message
                    WHERE id = %s
                    """,
                    (message_id,),
                )
                row = cur.fetchone()

        if not row:
            return None

        return self._row_to_message(row)

    def get_by_correlation_id(self, correlation_id: str) -> list[AgentMessage]:
        """Get all messages with a correlation ID."""
        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, message_id, sender_agent_id, recipient_agent_id,
                           mission_id, task_id, correlation_id, message_type,
                           priority, payload, status, created_at, delivered_at,
                           processed_at, expires_at, retry_count, max_retries,
                           error, metadata
                    FROM execution.agent_message
                    WHERE correlation_id = %s
                    ORDER BY created_at
                    """,
                    (correlation_id,),
                )
                rows = cur.fetchall()

        return [self._row_to_message(row) for row in rows]

    def get_messages_for_agent(
        self,
        agent_id: str,
        *,
        status: MessageStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentMessage]:
        """Get messages for a specific agent (sent or received)."""
        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT id, message_id, sender_agent_id, recipient_agent_id,
                           mission_id, task_id, correlation_id, message_type,
                           priority, payload, status, created_at, delivered_at,
                           processed_at, expires_at, retry_count, max_retries,
                           error, metadata
                    FROM execution.agent_message
                    WHERE (sender_agent_id = %s OR recipient_agent_id = %s)
                """
                params = [agent_id, agent_id]

                if status:
                    query += " AND status = %s"
                    params.append(status.value)

                query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, params)
                rows = cur.fetchall()

        return [self._row_to_message(row) for row in rows]

    def get_pending_messages(
        self,
        agent_id: str,
        *,
        limit: int = 100,
    ) -> list[AgentMessage]:
        """Get pending (undelivered) messages for an agent."""
        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, message_id, sender_agent_id, recipient_agent_id,
                           mission_id, task_id, correlation_id, message_type,
                           priority, payload, status, created_at, delivered_at,
                           processed_at, expires_at, retry_count, max_retries,
                           error, metadata
                    FROM execution.agent_message
                    WHERE recipient_agent_id = %s
                      AND status IN ('sent', 'delivered')
                      AND (expires_at IS NULL OR expires_at > %s)
                    ORDER BY
                        CASE priority
                            WHEN 'critical' THEN 1
                            WHEN 'high' THEN 2
                            WHEN 'normal' THEN 3
                            WHEN 'low' THEN 4
                        END,
                        created_at
                    LIMIT %s
                    """,
                    (agent_id, datetime.now(UTC), limit),
                )
                rows = cur.fetchall()

        return [self._row_to_message(row) for row in rows]

    def update_status(
        self,
        message_id: str,
        status: MessageStatus,
        error: str | None = None,
    ) -> AgentMessage | None:
        """Update message status."""
        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                now = datetime.now(UTC)
                delivered_at = now if status == MessageStatus.DELIVERED else None
                processed_at = now if status == MessageStatus.PROCESSED else None

                cur.execute(
                    """
                    UPDATE execution.agent_message
                    SET status = %s,
                        delivered_at = COALESCE(%s, delivered_at),
                        processed_at = COALESCE(%s, processed_at),
                        error = %s
                    WHERE id = %s
                    RETURNING id, message_id, sender_agent_id, recipient_agent_id,
                              mission_id, task_id, correlation_id, message_type,
                              priority, payload, status, created_at, delivered_at,
                              processed_at, expires_at, retry_count, max_retries,
                              error, metadata
                    """,
                    (
                        status.value,
                        delivered_at,
                        processed_at,
                        error,
                        message_id,
                    ),
                )
                row = cur.fetchone()
                conn.commit()

        if not row:
            return None

        message = self._row_to_message(row)

        # Update cache
        with self._lock:
            self._cache[message_id] = message

        return message

    def increment_retry(self, message_id: str) -> AgentMessage | None:
        """Increment retry count and reset status to SENT."""
        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution.agent_message
                    SET status = 'sent',
                        retry_count = retry_count + 1,
                        delivered_at = NULL,
                        processed_at = NULL,
                        error = NULL
                    WHERE id = %s
                    RETURNING id, message_id, sender_agent_id, recipient_agent_id,
                              mission_id, task_id, correlation_id, message_type,
                              priority, payload, status, created_at, delivered_at,
                              processed_at, expires_at, retry_count, max_retries,
                              error, metadata
                    """,
                    (message_id,),
                )
                row = cur.fetchone()
                conn.commit()

        if not row:
            return None

        return self._row_to_message(row)

    def delete_expired(self, before: datetime | None = None) -> int:
        """Delete expired messages."""
        if before is None:
            before = datetime.now(UTC)

        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM execution.agent_message
                    WHERE expires_at IS NOT NULL AND expires_at < %s
                    """,
                    (before,),
                )
                deleted = cur.rowcount
                conn.commit()

        self._logger.info("Deleted %d expired agent messages", deleted)
        return deleted

    def count_by_status(self, status: MessageStatus) -> int:
        """Count messages by status."""
        with self._pool_manager.get_sync_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM execution.agent_message WHERE status = %s",
                    (status.value,),
                )
                return cur.fetchone()[0]

    def _row_to_message(self, row: tuple) -> AgentMessage:
        """Convert database row to AgentMessage."""
        from types import MappingProxyType

        return AgentMessage(
            id=row[0],
            message_id=row[1],
            sender_agent_id=row[2],
            recipient_agent_id=row[3],
            mission_id=row[4],
            task_id=row[5],
            correlation_id=row[6],
            message_type=row[7],
            priority=row[8],
            payload=MappingProxyType(json.loads(row[9]) if row[9] else {}),
            status=row[10],
            created_at=row[11],
            delivered_at=row[12],
            processed_at=row[13],
            expires_at=row[14],
            retry_count=row[15],
            max_retries=row[16],
            error=row[17],
            metadata=MappingProxyType(json.loads(row[18]) if row[18] else {}),
        )