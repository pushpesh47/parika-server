"""
PARIKA Runtime Registry

Manages runtime/environment availability and health.
Reports availability facts only - does not perform selection.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.agent_runtime.contracts import (
    RuntimeCapabilities,
    RuntimeConfig,
    RuntimeInfo,
    RuntimeStatus,
    RuntimeType,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class RegisteredRuntime:
    """Registered runtime entry."""
    info: RuntimeInfo
    config: RuntimeConfig
    backend_instance: Any = None  # Optional backend instance for health checks


class RuntimeRegistry:
    """
    Registry for execution environment availability.
    
    Reports runtime/environment availability as facts.
    Does NOT perform runtime selection - that is done by ExecutionStrategyResolver.
    
    Manages:
    - Runtime registration and health status
    - Availability queries
    - Statistics
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
        runtime_type: RuntimeType,
        config: RuntimeConfig,
        backend_instance: Any = None,
    ) -> RuntimeInfo:
        """Register a runtime/environment."""
        with self._lock:
            if config.runtime_id in self._runtimes:
                raise ValueError(f"Runtime '{config.runtime_id}' already registered")

            info = RuntimeInfo(
                runtime_id=config.runtime_id,
                name=config.name,
                runtime_type=runtime_type,
                status=RuntimeStatus.STOPPED,
                capabilities=RuntimeCapabilities(),
                config=config,
            )

            entry = RegisteredRuntime(
                info=info,
                config=config,
                backend_instance=backend_instance,
            )

            self._runtimes[config.runtime_id] = entry
            self._type_index.setdefault(runtime_type, set()).add(config.runtime_id)
            self._status_index.setdefault(RuntimeStatus.STOPPED, set()).add(config.runtime_id)

            self._logger.info("Registered runtime '%s' (%s)", config.name, runtime_type.value)
            self._event_bus.publish("runtime.registered", {
                "runtime_id": config.runtime_id,
                "name": config.name,
                "type": runtime_type.value,
            })

            return info

    def unregister(self, runtime_id: str) -> None:
        """Unregister a runtime."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            if not entry:
                raise ValueError(f"Runtime '{runtime_id}' not found")

            self._type_index[entry.info.runtime_type].discard(runtime_id)
            self._status_index[entry.info.status].discard(runtime_id)
            del self._runtimes[runtime_id]

            self._logger.info("Unregistered runtime '%s'", runtime_id)
            self._event_bus.publish("runtime.unregistered", {"runtime_id": runtime_id})

    def get_info(self, runtime_id: str) -> RuntimeInfo | None:
        """Get runtime info by ID."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            return entry.info if entry else None

    def get_backend_instance(self, runtime_id: str) -> Any | None:
        """Get the backend instance for a runtime."""
        with self._lock:
            entry = self._runtimes.get(runtime_id)
            return entry.backend_instance if entry else None

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

    def is_available(self, runtime_type: RuntimeType) -> bool:
        """
        Check if a runtime type is available (has at least one RUNNING instance).
        
        This is the primary query used by ExecutionStrategyResolver.
        """
        with self._lock:
            runtime_ids = self._type_index.get(runtime_type, set())
            for rid in runtime_ids:
                entry = self._runtimes.get(rid)
                if entry and entry.info.status == RuntimeStatus.RUNNING:
                    return True
            return False

    def get_available_runtimes(self, runtime_type: RuntimeType) -> list[RuntimeInfo]:
        """Get all runtimes of a type that are RUNNING."""
        with self._lock:
            runtime_ids = self._type_index.get(runtime_type, set())
            return [
                self._runtimes[rid].info
                for rid in runtime_ids
                if rid in self._runtimes and self._runtimes[rid].info.status == RuntimeStatus.RUNNING
            ]

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