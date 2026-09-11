"""
PARIKA Implementation Registry

Manages multiple implementations per semantic capability.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.tool_manager.tool_manager import ToolManager

from .implementation import (
    CapabilityImplementation,
    ImplementationSource,
    ImplementationStatus,
    ImplementationMetadata,
    generate_implementation_id,
)


@dataclass(slots=True, kw_only=True)
class ImplementationFilter:
    """Filters for implementation queries."""
    capability_id: str | None = None
    source: ImplementationSource | None = None
    status: ImplementationStatus | None = None
    security_status: str | None = None
    runtime_type: str | None = None
    tags: tuple[str, ...] = ()
    required_tool: str | None = None
    required_skill: str | None = None
    min_experience_score: float = 0.0
    min_reliability_score: float = 0.0


class ImplementationRegistry:
    """
    Registry for capability implementations.

    Maintains multiple implementations per semantic capability.
    Supports filtering, validation, and selection.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        skill_registry: SkillRegistry,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._skill_registry = skill_registry
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = threading.RLock()

        # Implementations by ID
        self._implementations: dict[str, CapabilityImplementation] = {}

        # Index by capability_id
        self._capability_index: dict[str, set[str]] = {}

        # Index by source
        self._source_index: dict[ImplementationSource, set[str]] = {}

        # Index by status
        self._status_index: dict[ImplementationStatus, set[str]] = {}

        # Index by runtime_type
        self._runtime_index: dict[str, set[str]] = {}

        # Index by tags
        self._tag_index: dict[str, set[str]] = {}

    def register_implementation(
        self,
        capability_id: str,
        source: ImplementationSource,
        name: str,
        description: str,
        version: str,
        metadata: ImplementationMetadata,
    ) -> CapabilityImplementation:
        """
        Register a new capability implementation.

        Args:
            capability_id: The semantic capability this implements
            source: Source of the implementation
            name: Human-readable name
            description: Description of this implementation
            version: Version string
            metadata: Implementation metadata (runtime, tools, skills, etc.)

        Returns:
            The registered implementation
        """
        # Validate capability exists
        if not self._capability_registry.contains(capability_id):
            raise ValueError(f"Capability '{capability_id}' not registered")

        # Validate tools exist
        for tool_id in metadata.tool_ids:
            if not self._tool_manager.contains(tool_id):
                raise ValueError(f"Tool '{tool_id}' not registered")

        # Validate skills exist (if activated)
        for skill_id in metadata.skill_ids:
            skill = self._skill_registry.get_skill(skill_id)
            if not skill:
                raise ValueError(f"Skill '{skill_id}' not found in registry")

        implementation = CapabilityImplementation.create(
            capability_id=capability_id,
            source=source,
            name=name,
            description=description,
            version=version,
            metadata=metadata,
        )

        with self._lock:
            self._implementations[implementation.id] = implementation
            self._capability_index.setdefault(capability_id, set()).add(implementation.id)
            self._source_index.setdefault(source, set()).add(implementation.id)
            self._status_index.setdefault(ImplementationStatus.REGISTERED, set()).add(implementation.id)
            self._runtime_index.setdefault(metadata.runtime_type, set()).add(implementation.id)

            for tag in metadata.tags:
                self._tag_index.setdefault(tag, set()).add(implementation.id)

        self._logger.info(
            "Registered implementation '%s' for capability '%s' (source: %s)",
            implementation.id, capability_id, source.value
        )
        self._event_bus.publish("implementation.registered", {
            "implementation_id": implementation.id,
            "capability_id": capability_id,
            "source": source.value,
        })

        return implementation

    def unregister_implementation(self, implementation_id: str) -> None:
        """Unregister an implementation."""
        with self._lock:
            impl = self._implementations.get(implementation_id)
            if not impl:
                raise ValueError(f"Implementation '{implementation_id}' not found")

            self._capability_index[impl.capability_id].discard(implementation_id)
            self._source_index[impl.source].discard(implementation_id)
            self._status_index[impl.status].discard(implementation_id)
            self._runtime_index[impl.metadata.runtime_type].discard(implementation_id)

            for tag in impl.metadata.tags:
                self._tag_index.get(tag, set()).discard(implementation_id)

            del self._implementations[implementation_id]

        self._logger.info("Unregistered implementation '%s'", implementation_id)
        self._event_bus.publish("implementation.unregistered", {
            "implementation_id": implementation_id,
        })

    def get_implementation(self, implementation_id: str) -> CapabilityImplementation | None:
        """Get an implementation by ID."""
        with self._lock:
            return self._implementations.get(implementation_id)

    def get_implementations_for_capability(
        self,
        capability_id: str,
        *,
        status: ImplementationStatus | None = None,
        source: ImplementationSource | None = None,
    ) -> list[CapabilityImplementation]:
        """Get all implementations for a capability."""
        with self._lock:
            impl_ids = self._capability_index.get(capability_id, set())
            implementations = [
                self._implementations[iid]
                for iid in impl_ids
                if iid in self._implementations
            ]

        if status:
            implementations = [i for i in implementations if i.status == status]
        if source:
            implementations = [i for i in implementations if i.source == source]

        return implementations

    def list_implementations(self, filter: ImplementationFilter | None = None) -> list[CapabilityImplementation]:
        """List implementations matching filter."""
        with self._lock:
            if filter is None:
                return list(self._implementations.values())

            # Start with capability filter if specified
            if filter.capability_id:
                impl_ids = self._capability_index.get(filter.capability_id, set())
            else:
                impl_ids = set(self._implementations.keys())

            # Apply other filters
            if filter.source:
                impl_ids &= self._source_index.get(filter.source, set())
            if filter.status:
                impl_ids &= self._status_index.get(filter.status, set())
            if filter.runtime_type:
                impl_ids &= self._runtime_index.get(filter.runtime_type, set())
            if filter.tags:
                for tag in filter.tags:
                    impl_ids &= self._tag_index.get(tag, set())

            implementations = [
                self._implementations[iid]
                for iid in impl_ids
                if iid in self._implementations
            ]

            # Apply remaining filters
            if filter.security_status:
                implementations = [i for i in implementations if i.security_status == filter.security_status]
            if filter.required_tool:
                implementations = [i for i in implementations if filter.required_tool in i.metadata.tool_ids]
            if filter.required_skill:
                implementations = [i for i in implementations if filter.required_skill in i.metadata.skill_ids]
            if filter.min_experience_score > 0:
                implementations = [i for i in implementations if i.experience_score >= filter.min_experience_score]
            if filter.min_reliability_score > 0:
                implementations = [i for i in implementations if i.reliability_score >= filter.min_reliability_score]

            return implementations

    def update_implementation_status(
        self,
        implementation_id: str,
        status: ImplementationStatus,
        error: str | None = None,
    ) -> CapabilityImplementation:
        """Update implementation status."""
        with self._lock:
            impl = self._implementations.get(implementation_id)
            if not impl:
                raise ValueError(f"Implementation '{implementation_id}' not found")

            updated = CapabilityImplementation(
                id=impl.id,
                capability_id=impl.capability_id,
                source=impl.source,
                name=impl.name,
                description=impl.description,
                version=impl.version,
                metadata=impl.metadata,
                status=status,
                security_status=impl.security_status,
                experience_score=impl.experience_score,
                reliability_score=impl.reliability_score,
                avg_latency_ms=impl.avg_latency_ms,
                avg_cost=impl.avg_cost,
                created_at=impl.created_at,
                updated_at=datetime.now(UTC),
                last_used_at=impl.last_used_at,
                usage_count=impl.usage_count,
                success_count=impl.success_count,
                failure_count=impl.failure_count,
                error=error,
            )

            self._implementations[implementation_id] = updated
            self._status_index.get(impl.status, set()).discard(implementation_id)
            self._status_index.setdefault(status, set()).add(implementation_id)

            self._event_bus.publish("implementation.status_changed", {
                "implementation_id": implementation_id,
                "old_status": impl.status.value,
                "new_status": status.value,
            })

            return updated

    def update_security_status(
        self,
        implementation_id: str,
        security_status: str,
    ) -> CapabilityImplementation:
        """Update implementation security status."""
        with self._lock:
            impl = self._implementations.get(implementation_id)
            if not impl:
                raise ValueError(f"Implementation '{implementation_id}' not found")

            updated = CapabilityImplementation(
                id=impl.id,
                capability_id=impl.capability_id,
                source=impl.source,
                name=impl.name,
                description=impl.description,
                version=impl.version,
                metadata=impl.metadata,
                status=impl.status,
                security_status=security_status,
                experience_score=impl.experience_score,
                reliability_score=impl.reliability_score,
                avg_latency_ms=impl.avg_latency_ms,
                avg_cost=impl.avg_cost,
                created_at=impl.created_at,
                updated_at=datetime.now(UTC),
                last_used_at=impl.last_used_at,
                usage_count=impl.usage_count,
                success_count=impl.success_count,
                failure_count=impl.failure_count,
                error=impl.error,
            )

            self._implementations[implementation_id] = updated

            self._event_bus.publish("implementation.security_changed", {
                "implementation_id": implementation_id,
                "security_status": security_status,
            })

            return updated

    def record_execution_result(
        self,
        implementation_id: str,
        success: bool,
        latency_ms: float,
        cost: float = 0.0,
        error: str | None = None,
    ) -> CapabilityImplementation:
        """Record execution result for experience tracking."""
        with self._lock:
            impl = self._implementations.get(implementation_id)
            if not impl:
                raise ValueError(f"Implementation '{implementation_id}' not found")

        if success:
            updated = impl.record_success(latency_ms, cost)
        else:
            updated = impl.record_failure(error or "Unknown error")

        with self._lock:
            self._implementations[implementation_id] = updated

        return updated

    def validate_implementation(self, implementation_id: str) -> bool:
        """Validate an implementation's dependencies."""
        with self._lock:
            impl = self._implementations.get(implementation_id)
            if not impl:
                return False

        # Check capability still exists
        if not self._capability_registry.contains(impl.capability_id):
            return False

        # Check tools still exist
        for tool_id in impl.metadata.tool_ids:
            if not self._tool_manager.contains(tool_id):
                return False

        # Check skills are available
        for skill_id in impl.metadata.skill_ids:
            skill = self._skill_registry.get_skill(skill_id)
            if not skill or not skill.is_activatable():
                return False

        # Check runtime compatibility
        # This would check if the required runtime is available

        return True

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            return {
                "total_implementations": len(self._implementations),
                "by_capability": {
                    cap: len(ids) for cap, ids in self._capability_index.items()
                },
                "by_source": {
                    src.value: len(ids) for src, ids in self._source_index.items()
                },
                "by_status": {
                    st.value: len(ids) for st, ids in self._status_index.items()
                },
                "by_runtime": {
                    rt: len(ids) for rt, ids in self._runtime_index.items()
                },
            }