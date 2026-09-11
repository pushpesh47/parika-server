"""
PARIKA Runtime Registry

Manages available runtimes and their lifecycle.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from parika.core.agent_runtime.contracts import (
    AgentRuntime,
    RuntimeConfig,
    RuntimeInfo,
    RuntimeStatus,
    RuntimeType,
    RuntimeCapabilities,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class RegisteredRuntime:
    """Registered runtime entry."""
    runtime: AgentRuntime
    info: RuntimeInfo
    config: RuntimeConfig


class RuntimeRegistry:
    """
    Registry for agent runtimes.

    Manages runtime discovery, registration, and lifecycle.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = threading.RLock()

        # Runtimes by ID
        self._runtimes: dict[str, RegisteredRuntime] = {}

        # Index by type
        self._type_index: dict[RuntimeType, set[str]] = {}

        # Index by status
        self._status_index: dict[RuntimeStatus, set[str]] = {}

    def register(
        self,
        runtime: AgentRuntime,
        config: RuntimeConfig,
    ) -> RuntimeInfo:
        """Register a runtime."""
        with self._lock:
            if runtime.runtime_id in self._runtimes:
                raise ValueError(f"Runtime '{runtime.runtime_id}' already registered")

            info = RuntimeInfo(
                runtime_id=runtime.runtime_id,
                name=config.name,
                runtime_type=runtime.runtime_type,
                status=RuntimeStatus.STOPPED,
                capabilities=runtime.capabilities,
                config=config,
            )

            entry = RegisteredRuntime(
                runtime=runtime,
                info=info,
                config=config,
            )

            self._runtimes[runtime.runtime_id] = entry
            self._type_index.setdefault(runtime.runtime_type, set()).add(runtime.runtime_id)
            self._status_index.setdefault(RuntimeStatus.STOPPED, set()).add(runtime.runtime_id)

            self._logger.info("Registered runtime '%s' (%s)", config.name, runtime.runtime_type.value)
            self._event_bus.publish("runtime.registered", {
                "runtime_id": runtime.runtime_id,
                "name": config.name,
                "type": runtime.runtime_type.value,
            })

            return info

    def unregister(self, runtime_id: str) -> None:
        """Unregister a runtime."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if not entry:
                raise ValueError(f"Runtime '{runtime_id}' not found")

            # Stop if running
            if entry.info.status == RuntimeStatus.RUNNING:
                entry.runtime.stop()

            self._type_index[entry.runtime.runtime_type].discard(runtime_id)
            self._status_index[entry.info.status].discard(runtime_id)
            del self._runtimes[runtime_id]

            self._logger.info("Unregistered runtime '%s'", runtime_id)
            self._event_bus.publish("runtime.unregistered", {"runtime_id": runtime_id})

    def get_runtime(self, runtime_id: str) -> AgentRuntime | None:
        """Get a runtime by ID."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            return entry.runtime if entry else None

    def get_info(self, runtime_id: str) -> RuntimeInfo | None:
        """Get runtime info by ID."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            return entry.info if entry else None

    def list_runtimes(
        self,
        *,
        runtime_type: RuntimeType | None = None,
        status: RuntimeStatus | None = None,
    ) -> list[RuntimeInfo]:
        """List runtimes matching filters."""
        with self._lock:
            if runtime_type:
                runtime_ids = self._type_index.get(runtime_type, set())
            elif status:
                runtime_ids = self._status_index.get(status, set())
            else:
                runtime_ids = set(self._runtimes.keys())

            return [
                self._runtimes[rid].info
                for rid in runtime_ids
                if rid in self._runtimes
            ]

    def update_status(self, runtime_id: str, status: RuntimeStatus, error: str | None = None) -> RuntimeInfo | None:
        """Update runtime status."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if not entry:
                return None

            old_status = entry.info.status
            if old_status != status:
                self._status_index.get(old_status, set()).discard(runtime_id)
                self._status_index.setdefault(status, set()).add(runtime_id)

            # Create new info with updated status
            updated_info = RuntimeInfo(
                runtime_id=entry.info.runtime_id,
                name=entry.info.name,
                runtime_type=entry.info.runtime_type,
                status=status,
                capabilities=entry.info.capabilities,
                config=entry.info.config,
                started_at=entry.info.started_at,
                last_heartbeat=datetime.now(UTC) if status == RuntimeStatus.RUNNING else entry.info.last_heartbeat,
                active_agents=entry.info.active_agents,
                error=error,
            )

            entry.info = updated_info

            self._event_bus.publish("runtime.status_changed", {
                "runtime_id": runtime_id,
                "old_status": old_status.value,
                "new_status": status.value,
            })

            return updated_info

    def start_runtime(self, runtime_id: str) -> RuntimeInfo | None:
        """Start a runtime."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if not entry:
                return None

        # Start outside lock
        success = entry.runtime.start()

        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if not entry:
                return None

            if success:
                entry.info = RuntimeInfo(
                    runtime_id=entry.info.runtime_id,
                    name=entry.info.name,
                    runtime_type=entry.info.runtime_type,
                    status=RuntimeStatus.RUNNING,
                    capabilities=entry.info.capabilities,
                    config=entry.info.config,
                    started_at=datetime.now(UTC),
                    last_heartbeat=datetime.now(UTC),
                    active_agents=entry.info.active_agents,
                )
            else:
                entry.info = RuntimeInfo(
                    runtime_id=entry.info.runtime_id,
                    name=entry.info.name,
                    runtime_type=entry.info.runtime_type,
                    status=RuntimeStatus.ERROR,
                    capabilities=entry.info.capabilities,
                    config=entry.info.config,
                    error="Failed to start",
                )

            return entry.info

    def stop_runtime(self, runtime_id: str) -> bool:
        """Stop a runtime."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if not entry:
                return False

        success = entry.runtime.stop()

        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if entry:
                entry.info = RuntimeInfo(
                    runtime_id=entry.info.runtime_id,
                    name=entry.info.name,
                    runtime_type=entry.info.runtime_type,
                    status=RuntimeStatus.STOPPED if success else RuntimeStatus.ERROR,
                    capabilities=entry.info.capabilities,
                    config=entry.info.config,
                    started_at=entry.info.started_at,
                    error=None if success else "Failed to stop",
                )

        return success

    def increment_active_agents(self, runtime_id: str) -> int:
        """Increment active agent count."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if not entry:
                return 0
            entry.info = RuntimeInfo(
                runtime_id=entry.info.runtime_id,
                name=entry.info.name,
                runtime_type=entry.info.runtime_type,
                status=entry.info.status,
                capabilities=entry.info.capabilities,
                config=entry.info.config,
                started_at=entry.info.started_at,
                last_heartbeat=entry.info.last_heartbeat,
                active_agents=entry.info.active_agents + 1,
                error=entry.info.error,
            )
            return entry.info.active_agents

    def decrement_active_agents(self, runtime_id: str) -> int:
        """Decrement active agent count."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if not entry:
                return 0
            new_count = max(0, entry.info.active_agents - 1)
            entry.info = RuntimeInfo(
                runtime_id=entry.info.runtime_id,
                name=entry.info.name,
                runtime_type=entry.info.runtime_type,
                status=entry.info.status,
                capabilities=entry.info.capabilities,
                config=entry.info.config,
                started_at=entry.info.started_at,
                last_heartbeat=entry.info.last_heartbeat,
                active_agents=new_count,
                error=entry.info.error,
            )
            return new_count

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            return {
                "total_runtimes": len(self._runtimes),
                "by_type": {
                    rt.value: len(ids) for rt, ids in self._type_index.items()
                },
                "by_status": {
                    st.value: len(ids) for st, ids in self._status_index.items()
                },
                "total_active_agents": sum(
                    e.info.active_agents for e in self._runtimes.values()
                ),
            }