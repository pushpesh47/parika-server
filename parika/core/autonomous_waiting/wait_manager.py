"""
PARIKA Wait Manager

Manages wait conditions and event-driven wake-up for autonomous tasks.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Callable

from parika.core.autonomous.task_manager import AutonomousTaskManager
from parika.core.autonomous.contracts import AutonomousTaskStatus
from parika.core.autonomous_waiting.wait_condition import (
    WaitCondition,
    WaitConditionType,
    WaitConditionStatus,
)
from parika.core.agent_communication.message_bus import MessageBus
from parika.core.agent_communication.message import AgentMessage, MessageType
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class WaitConditionRegistration:
    """Registered wait condition with callback."""
    condition: WaitCondition
    callback: Callable[[WaitCondition], None] | None = None


class WaitManager:
    """
    Manages wait conditions and event-driven wake-up.

    Integrates with:
    - EventBus for event matching
    - MessageBus for agent message waiting
    - TaskManager for dependency waiting
    - ResourceManager for resource waiting

    When a task enters a waiting state, it registers a wait condition.
    The WaitManager monitors relevant events and wakes tasks when
    their conditions are satisfied.
    """

    def __init__(
        self,
        *,
        task_manager: AutonomousTaskManager,
        message_bus: MessageBus,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._task_manager = task_manager
        self._message_bus = message_bus
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = threading.RLock()

        # Wait conditions by task_id
        self._task_waits: dict[str, list[WaitCondition]] = {}

        # Wait conditions by type for efficient lookup
        self._type_index: dict[WaitConditionType, set[str]] = {}

        # Event subscribers for different condition types
        self._event_subscriptions: dict[str, Callable] = {}

        # Running state
        self._running = False

        # Subscribe to relevant events
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        """Subscribe to events that can satisfy wait conditions."""
        # Task completion events
        self._event_bus.subscribe("task.completed", self._on_task_completed)
        self._event_bus.subscribe("task.failed", self._on_task_failed)

        # Agent message events
        self._event_bus.subscribe("agent.message.sent", self._on_agent_message)
        self._event_bus.subscribe("agent.message.delivered", self._on_agent_message_delivered)

        # Resource events (would come from ResourceManager)
        # self._event_bus.subscribe("resource.available", self._on_resource_available)

        # Approval events
        self._event_bus.subscribe("approval.granted", self._on_approval_granted)
        self._event_bus.subscribe("approval.denied", self._on_approval_denied)

        # File system events (would come from file watcher)
        # self._event_bus.subscribe("file.created", self._on_file_created)

        # Time events (handled by scheduler)
        # self._event_bus.subscribe("time.wake", self._on_time_wake)

    def register_wait(
        self,
        condition: WaitCondition,
        callback: Callable[[WaitCondition], None] | None = None,
    ) -> WaitCondition:
        """
        Register a wait condition for a task.

        The task should transition to WAITING state before calling this.
        """
        with self._lock:
            # Add to task index
            self._task_waits.setdefault(condition.task_id, []).append(condition)
            self._type_index.setdefault(condition.condition_type, set()).add(condition.id)

        # Update condition status
        updated = condition.with_status(WaitConditionStatus.WAITING)

        with self._lock:
            # Replace in list
            task_waits = self._task_waits.get(condition.task_id, [])
            for i, w in enumerate(task_waits):
                if w.id == condition.id:
                    task_waits[i] = updated
                    break

        self._logger.info(
            "Registered wait condition '%s' for task '%s' (type: %s)",
            condition.id, condition.task_id, condition.condition_type.value
        )

        self._event_bus.publish("wait.condition.registered", {
            "wait_id": condition.id,
            "task_id": condition.task_id,
            "condition_type": condition.condition_type.value,
        })

        return updated

    def check_condition(self, condition: WaitCondition, event_data: MappingProxyType[str, Any]) -> bool:
        """
        Check if an event satisfies a wait condition.

        Returns True if condition is satisfied.
        """
        if condition.status != WaitConditionStatus.WAITING:
            return False

        if condition.is_expired():
            self._logger.warning("Wait condition '%s' expired", condition.id)
            return False

        # Check based on condition type
        if condition.condition_type == WaitConditionType.DEPENDENCY:
            return self._check_dependency(condition, event_data)
        elif condition.condition_type == WaitConditionType.AGENT_MESSAGE:
            return self._check_agent_message(condition, event_data)
        elif condition.condition_type == WaitConditionType.APPROVAL:
            return self._check_approval(condition, event_data)
        elif condition.condition_type == WaitConditionType.EXTERNAL_EVENT:
            return self._check_external_event(condition, event_data)
        elif condition.condition_type == WaitConditionType.TIME:
            return self._check_time(condition, event_data)
        elif condition.condition_type == WaitConditionType.RESOURCE:
            return self._check_resource(condition, event_data)
        elif condition.condition_type == WaitConditionType.FILE_EXISTS:
            return self._check_file(condition, event_data)

        return False

    def _check_dependency(self, condition: WaitCondition, event_data: MappingProxyType[str, Any]) -> bool:
        """Check if dependency wait is satisfied."""
        depends_on = condition.condition_data.get("depends_on_task_ids", [])
        if not depends_on:
            return False

        completed_task = event_data.get("task_id")
        if not completed_task:
            return False

        # Check if completed task is in our dependencies
        if completed_task in depends_on:
            # Check if all dependencies are satisfied
            task = self._task_manager.get(condition.task_id)
            if not task:
                return False

            all_deps = set(task.metadata.get("depends_on", []))
            completed_deps = set(event_data.get("completed_dependencies", []))
            completed_deps.add(completed_task)

            return all_deps.issubset(completed_deps)

        return False

    def _check_agent_message(self, condition: WaitCondition, event_data: MappingProxyType[str, Any]) -> bool:
        """Check if agent message wait is satisfied."""
        expected_type = condition.condition_data.get("expected_message_type")
        from_agent = condition.condition_data.get("from_agent_id")
        correlation_id = condition.condition_data.get("correlation_id")

        msg_type = event_data.get("message_type")
        sender = event_data.get("sender_agent_id")
        corr_id = event_data.get("correlation_id")

        if expected_type and msg_type != expected_type:
            return False

        if from_agent and sender != from_agent:
            return False

        if correlation_id and corr_id != correlation_id:
            return False

        return True

    def _check_approval(self, condition: WaitCondition, event_data: MappingProxyType[str, Any]) -> bool:
        """Check if approval wait is satisfied."""
        approval_id = condition.condition_data.get("approval_id")
        event_approval_id = event_data.get("approval_id")

        return approval_id == event_approval_id

    def _check_external_event(self, condition: WaitCondition, event_data: MappingProxyType[str, Any]) -> bool:
        """Check if external event wait is satisfied."""
        event_source = condition.condition_data.get("event_source")
        event_type = condition.condition_data.get("event_type")
        event_filter = condition.condition_data.get("event_filter", {})

        if event_source and event_data.get("source") != event_source:
            return False

        if event_type and event_data.get("type") != event_type:
            return False

        # Check filter
        for key, value in event_filter.items():
            if event_data.get(key) != value:
                return False

        return True

    def _check_resource(self, condition: WaitCondition, event_data: MappingProxyType[str, Any]) -> bool:
        """Check if resource wait is satisfied."""
        # Would check against ResourceManager
        resource_type = condition.condition_data.get("resource_type")
        required = condition.condition_data.get("required_amount", 0)

        available = event_data.get("available", 0)
        return available >= required

    def _check_time(self, condition: WaitCondition, event_data: MappingProxyType[str, Any]) -> bool:
        """Check if time wait is satisfied."""
        wake_at_str = condition.condition_data.get("wake_at")
        if not wake_at_str:
            return False

        try:
            wake_at = datetime.fromisoformat(wake_at_str)
            return datetime.now(UTC) >= wake_at
        except ValueError:
            return False

    def _check_file(self, condition: WaitCondition, event_data: MappingProxyType[str, Any]) -> bool:
        """Check if file wait is satisfied."""
        file_path = condition.condition_data.get("file_path")
        if not file_path:
            return False

        # Check if file exists event
        if event_data.get("file_path") == file_path:
            return True

        # Also check directly
        from pathlib import Path
        return Path(file_path).exists()

    def _on_task_completed(self, event_data: Any) -> None:
        """Handle task completed event."""
        self._check_and_wake_tasks(event_data)

    def _on_task_failed(self, event_data: Any) -> None:
        """Handle task failed event."""
        self._check_and_wake_tasks(event_data)

    def _on_agent_message(self, event_data: Any) -> None:
        """Handle agent message sent event."""
        self._check_wait_conditions(WaitConditionType.AGENT_MESSAGE, event_data)

    def _on_agent_message_delivered(self, event_data: Any) -> None:
        """Handle agent message delivered event."""
        self._check_wait_conditions(WaitConditionType.AGENT_MESSAGE, event_data)

    def _on_approval_granted(self, event_data: Any) -> None:
        """Handle approval granted event."""
        self._check_wait_conditions(WaitConditionType.APPROVAL, event_data)

    def _on_approval_denied(self, event_data: Any) -> None:
        """Handle approval denied event."""
        self._check_wait_conditions(WaitConditionType.APPROVAL, event_data)

    def _check_and_wake_tasks(self, event_data: Any) -> None:
        """Check dependency waits and wake tasks."""
        self._check_wait_conditions(WaitConditionType.DEPENDENCY, event_data)

    def _check_wait_conditions(
        self,
        condition_type: WaitConditionType,
        event_data: MappingProxyType[str, Any],
    ) -> None:
        """Check all wait conditions of a type against event data."""
        condition_ids = self._type_index.get(condition_type, set())

        for condition_id in list(condition_ids):
            # Find the condition
            condition = None
            for waits in self._task_waits.values():
                for w in waits:
                    if w.id == condition_id:
                        condition = w
                        break
                if condition:
                    break

            if not condition:
                continue

            if self.check_condition(condition, event_data):
                self._satisfy_condition(condition)

    def _satisfy_condition(self, condition: WaitCondition) -> None:
        """Mark condition as satisfied and wake the task."""
        updated = condition.with_status(WaitConditionStatus.SATISFIED)

        with self._lock:
            # Update in task waits
            task_waits = self._task_waits.get(condition.task_id, [])
            for i, w in enumerate(task_waits):
                if w.id == condition.id:
                    task_waits[i] = updated
                    break

            # Remove from type index
            self._type_index.get(condition.condition_type, set()).discard(condition.id)

        # Wake the task
        task = self._task_manager.get(condition.task_id)
        if task and task.status == AutonomousTaskStatus.WAITING_FOR_DEPENDENCY:
            self._task_manager.resume(condition.task_id)
            self._logger.info(
                "Woke task '%s' due to satisfied wait condition '%s'",
                condition.task_id, condition.id
            )

        self._event_bus.publish("wait.condition.satisfied", {
            "wait_id": condition.id,
            "task_id": condition.task_id,
            "condition_type": condition.condition_type.value,
        })

    def cancel_wait(self, task_id: str, wait_id: str | None = None) -> int:
        """Cancel wait condition(s) for a task."""
        with self._lock:
            waits = self._task_waits.get(task_id, [])
            if not waits:
                return 0

            if wait_id:
                # Cancel specific wait
                for i, w in enumerate(waits):
                    if w.id == wait_id:
                        updated = w.with_status(WaitConditionStatus.CANCELLED)
                        waits[i] = updated
                        self._type_index.get(w.condition_type, set()).discard(w.id)
                        return 1
                return 0
            else:
                # Cancel all waits for task
                count = 0
                for w in waits:
                    if w.status == WaitConditionStatus.WAITING:
                        updated = w.with_status(WaitConditionStatus.CANCELLED)
                        waits[waits.index(w)] = updated
                        self._type_index.get(w.condition_type, set()).discard(w.id)
                        count += 1
                return count

    def get_waits_for_task(self, task_id: str) -> list[WaitCondition]:
        """Get all wait conditions for a task."""
        with self._lock:
            return list(self._task_waits.get(task_id, []))

    def get_pending_waits(self) -> list[WaitCondition]:
        """Get all pending wait conditions."""
        with self._lock:
            result = []
            for waits in self._task_waits.values():
                for w in waits:
                    if w.status == WaitConditionStatus.WAITING:
                        result.append(w)
            return result

    def cleanup_expired(self) -> int:
        """Clean up expired wait conditions."""
        expired_count = 0
        with self._lock:
            for task_id, waits in self._task_waits.items():
                for i, w in enumerate(waits):
                    if w.status == WaitConditionStatus.WAITING and w.is_expired():
                        updated = w.with_status(WaitConditionStatus.EXPIRED)
                        waits[i] = updated
                        self._type_index.get(w.condition_type, set()).discard(w.id)
                        expired_count += 1

                        # Also fail the task if it was waiting
                        task = self._task_manager.get(w.task_id)
                        if task and task.status == AutonomousTaskStatus.WAITING_FOR_DEPENDENCY:
                            self._task_manager.fail(w.task_id, f"Wait condition '{w.id}' expired")

        if expired_count > 0:
            self._logger.warning("Cleaned up %d expired wait conditions", expired_count)

        return expired_count

    def get_stats(self) -> dict[str, Any]:
        """Get wait manager statistics."""
        with self._lock:
            total = sum(len(w) for w in self._task_waits.values())
            waiting = sum(
                1 for waits in self._task_waits.values()
                for w in waits if w.status == WaitConditionStatus.WAITING
            )
            by_type = {
                t.value: len(ids) for t, ids in self._type_index.items()
            }

        return {
            "total_conditions": total,
            "waiting": waiting,
            "by_type": by_type,
        }