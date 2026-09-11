"""
PARIKA Agent Message Bus

Provides message delivery between agents with persistence and retry.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Callable

from parika.core.agent_communication.message import (
    AgentMessage,
    MessageStatus,
    MessagePriority,
    MessageType,
)
# Phase 2 - AgentMessageRepository (lazy import to avoid circular dependency)
try:
    from parika.core.agent_communication.message_repository import AgentMessageRepository
except ImportError:
    AgentMessageRepository = None

from parika.core.autonomous.agent_supervisor import AgentSupervisor
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class MessageHandler:
    """Registered message handler."""
    agent_id: str
    message_types: tuple[MessageType, ...]
    handler: Callable[[AgentMessage], Any]


class MessageBus:
    """
    Bus for agent-to-agent message delivery.

    Handles:
    - Message persistence
    - Delivery to recipients
    - Retry logic
    - Event publishing
    - Handler registration
    """

    def __init__(
        self,
        *,
        repository: AgentMessageRepository,
        agent_supervisor: AgentSupervisor,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._repository = repository
        self._agent_supervisor = agent_supervisor
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = threading.RLock()
        self._handlers: dict[str, MessageHandler] = {}
        self._running = False
        self._delivery_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def register_handler(
        self,
        agent_id: str,
        message_types: tuple[MessageType, ...],
        handler: Callable[[AgentMessage], Any],
    ) -> None:
        """Register a message handler for an agent."""
        with self._lock:
            handler_obj = MessageHandler(
                agent_id=agent_id,
                message_types=message_types,
                handler=handler,
            )
            self._handlers[agent_id] = handler_obj

            self._logger.debug(
                "Registered message handler for agent '%s' (types: %s)",
                agent_id, [t.value for t in message_types]
            )

    def unregister_handler(self, agent_id: str) -> None:
        """Unregister a message handler."""
        with self._lock:
            if agent_id in self._handlers:
                del self._handlers[agent_id]
                self._logger.debug("Unregistered message handler for agent '%s'", agent_id)

    async def start(self) -> None:
        """Start the message delivery loop."""
        if self._running:
            return

        self._running = True
        self._loop = asyncio.get_event_loop()
        self._delivery_task = self._loop.create_task(self._delivery_loop())
        self._logger.info("Message bus started")

    async def stop(self) -> None:
        """Stop the message delivery loop."""
        if not self._running:
            return

        self._running = False
        if self._delivery_task:
            self._delivery_task.cancel()
            try:
                await self._delivery_task
            except asyncio.CancelledError:
                pass
        self._logger.info("Message bus stopped")

    def send(
        self,
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
    ) -> AgentMessage:
        """
        Send a message to another agent.

        Args:
            sender_agent_id: ID of sending agent
            recipient_agent_id: ID of recipient agent (None for broadcast)
            mission_id: Mission ID
            message_type: Type of message
            payload: Message payload
            task_id: Optional task ID
            correlation_id: Optional correlation ID
            priority: Message priority
            expires_at: Optional expiration time
            max_retries: Maximum retry attempts
            metadata: Optional metadata

        Returns:
            The created message
        """
        message = AgentMessage.create(
            sender_agent_id=sender_agent_id,
            recipient_agent_id=recipient_agent_id,
            mission_id=mission_id,
            message_type=message_type,
            payload=payload,
            task_id=task_id,
            correlation_id=correlation_id,
            priority=priority,
            expires_at=expires_at,
            max_retries=max_retries,
            metadata=metadata,
        )

        # Persist message
        self._repository.create(message)

        # Publish event
        self._event_bus.publish("agent.message.sent", {
            "message_id": message.id,
            "sender_agent_id": sender_agent_id,
            "recipient_agent_id": recipient_agent_id,
            "mission_id": mission_id,
            "message_type": message_type.value,
        })

        self._logger.debug(
            "Sent message '%s' from '%s' to '%s'",
            message.id, sender_agent_id, recipient_agent_id
        )

        return message

    async def send_async(
        self,
        sender_agent_id: str,
        recipient_agent_id: str | None,
        mission_id: str,
        message_type: MessageType,
        payload: MappingProxyType[str, Any],
        **kwargs,
    ) -> AgentMessage:
        """Send a message asynchronously."""
        # For now, same as sync - could be made truly async later
        return self.send(
            sender_agent_id=sender_agent_id,
            recipient_agent_id=recipient_agent_id,
            mission_id=mission_id,
            message_type=message_type,
            payload=payload,
            **kwargs,
        )

    def deliver(self, message_id: str) -> AgentMessage | None:
        """Mark a message as delivered and invoke handler."""
        message = self._repository.get(message_id)
        if not message:
            return None

        if message.status != MessageStatus.SENT:
            return None

        # Update status to DELIVERED
        message = self._repository.update_status(message_id, MessageStatus.DELIVERED)
        if not message:
            return None

        # Invoke handler if registered
        if message.recipient_agent_id:
            self._invoke_handler(message)

        return message

    def process(self, message_id: str, result: MappingProxyType[str, Any] | None = None) -> AgentMessage | None:
        """Mark a message as processed."""
        message = self._repository.get(message_id)
        if not message:
            return None

        if message.status not in (MessageStatus.DELIVERED, MessageStatus.PROCESSING):
            return None

        # Update status to PROCESSED
        message = self._repository.update_status(message_id, MessageStatus.PROCESSED)
        if not message:
            return None

        # If there's a correlation ID and this was a request, could auto-reply
        # For now, just return the processed message
        return message

    def _invoke_handler(self, message: AgentMessage) -> None:
        """Invoke registered handler for a message."""
        with self._lock:
            handler = self._handlers.get(message.recipient_agent_id)

        if not handler:
            self._logger.debug("No handler registered for agent '%s'", message.recipient_agent_id)
            return

        if message.message_type not in handler.message_types:
            return

        # Update status to PROCESSING
        self._repository.update_status(message.id, MessageStatus.PROCESSING)

        try:
            # Call handler
            if asyncio.iscoroutinefunction(handler.handler):
                # Schedule async handler
                if self._loop:
                    self._loop.create_task(handler.handler(message))
            else:
                # Call sync handler
                handler.handler(message)

            self._logger.debug(
                "Invoked handler for agent '%s' message '%s'",
                message.recipient_agent_id, message.id
            )

        except Exception as e:
            self._logger.error(
                "Handler for agent '%s' failed on message '%s': %s",
                message.recipient_agent_id, message.id, e
            )
            self._repository.update_status(message.id, MessageStatus.FAILED, str(e))

    async def _delivery_loop(self) -> None:
        """Background loop to deliver pending messages."""
        while self._running:
            try:
                # Get all active agents
                agents = self._agent_supervisor.get_all_active_agents()

                for agent in agents:
                    # Get pending messages for this agent
                    pending = self._repository.get_pending_messages(agent.id, limit=50)

                    for message in pending:
                        # Check expiration
                        if message.is_expired():
                            self._repository.update_status(
                                message.id, MessageStatus.EXPIRED,
                                "Message expired"
                            )
                            continue

                        # Deliver
                        self.deliver(message.id)

                # Wait before next cycle
                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("Error in message delivery loop: %s", e)
                await asyncio.sleep(5)

    def retry_failed(self, agent_id: str | None = None) -> int:
        """Retry failed messages."""
        retried = 0

        if agent_id:
            messages = self._repository.get_messages_for_agent(
                agent_id, status=MessageStatus.FAILED
            )
        else:
            # Would need a query for all failed messages
            pass

        for message in messages:
            if message.can_retry():
                self._repository.increment_retry(message.id)
                retried += 1

        return retried

    def get_stats(self) -> dict[str, Any]:
        """Get message bus statistics."""
        return {
            "registered_handlers": len(self._handlers),
            "running": self._running,
            "by_status": {
                s.value: self._repository.count_by_status(s)
                for s in MessageStatus
            },
        }