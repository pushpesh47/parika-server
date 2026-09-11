"""
PARIKA Capability Implementation Models

Defines the implementation layer above semantic capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class ImplementationSource(StrEnum):
    """Source of the implementation."""
    PARIKA_NATIVE = "parika_native"
    COMMUNITY = "community"
    HERMES = "hermes"
    REMOTE = "remote"
    CUSTOM = "custom"


class ImplementationStatus(StrEnum):
    """Implementation lifecycle status."""
    REGISTERED = "registered"
    VALIDATED = "validated"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True, slots=True, kw_only=True)
class ImplementationMetadata:
    """Metadata for a capability implementation."""
    runtime_type: str  # "native", "hermes", "remote"
    runtime_config: MappingProxyType[str, Any] = MappingProxyType({})
    tool_ids: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    required_environment: MappingProxyType[str, Any] = MappingProxyType({})
    resource_requirements: MappingProxyType[str, Any] = MappingProxyType({})
    compatibility: MappingProxyType[str, Any] = MappingProxyType({})
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_type": self.runtime_type,
            "runtime_config": dict(self.runtime_config),
            "tool_ids": list(self.tool_ids),
            "skill_ids": list(self.skill_ids),
            "required_capabilities": list(self.required_capabilities),
            "required_environment": dict(self.required_environment),
            "resource_requirements": dict(self.resource_requirements),
            "compatibility": dict(self.compatibility),
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityImplementation:
    """
    An implementation of a semantic capability.

    Multiple implementations can exist for one capability_id.
    Selection is based on hard gates + fitness scoring.
    """
    id: str
    capability_id: str
    source: ImplementationSource
    name: str
    description: str
    version: str
    metadata: ImplementationMetadata
    status: ImplementationStatus = ImplementationStatus.REGISTERED
    security_status: str = "approved"  # "approved", "warning", "blocked"
    experience_score: float = 0.5  # 0.0 - 1.0, from historical success
    reliability_score: float = 0.5  # 0.0 - 1.0
    avg_latency_ms: float = 0.0
    avg_cost: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime | None = None
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capability_id": self.capability_id,
            "source": self.source.value,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "metadata": self.metadata.to_dict(),
            "status": self.status.value,
            "security_status": self.security_status,
            "experience_score": self.experience_score,
            "reliability_score": self.reliability_score,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_cost": self.avg_cost,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "error": self.error,
        }

    def success_rate(self) -> float:
        """Calculate success rate from usage statistics."""
        if self.usage_count == 0:
            return self.experience_score
        return self.success_count / self.usage_count

    def is_healthy(self) -> bool:
        """Check if implementation is healthy for selection."""
        return (
            self.status == ImplementationStatus.ACTIVE
            and self.security_status != "blocked"
            and self.reliability_score > 0.3
        )

    def record_success(self, latency_ms: float, cost: float = 0.0) -> "CapabilityImplementation":
        """Record a successful execution."""
        now = datetime.now(UTC)
        new_usage = self.usage_count + 1
        new_success = self.success_count + 1

        # Update rolling averages
        new_avg_latency = (
            (self.avg_latency_ms * self.usage_count + latency_ms) / new_usage
            if self.usage_count > 0 else latency_ms
        )
        new_avg_cost = (
            (self.avg_cost * self.usage_count + cost) / new_usage
            if self.usage_count > 0 else cost
        )

        # Update experience score (weighted toward recent)
        alpha = 0.1
        new_experience = (1 - alpha) * self.experience_score + alpha * 1.0
        new_reliability = (1 - alpha) * self.reliability_score + alpha * 1.0

        return CapabilityImplementation(
            id=self.id,
            capability_id=self.capability_id,
            source=self.source,
            name=self.name,
            description=self.description,
            version=self.version,
            metadata=self.metadata,
            status=self.status,
            security_status=self.security_status,
            experience_score=new_experience,
            reliability_score=new_reliability,
            avg_latency_ms=new_avg_latency,
            avg_cost=new_avg_cost,
            created_at=self.created_at,
            updated_at=now,
            last_used_at=now,
            usage_count=new_usage,
            success_count=new_success,
            failure_count=self.failure_count,
            error=self.error,
        )

    def record_failure(self, error: str) -> "CapabilityImplementation":
        """Record a failed execution."""
        now = datetime.now(UTC)
        new_usage = self.usage_count + 1
        new_failure = self.failure_count + 1

        # Update experience score (weighted toward recent)
        alpha = 0.1
        new_experience = (1 - alpha) * self.experience_score + alpha * 0.0
        new_reliability = (1 - alpha) * self.reliability_score + alpha * 0.0

        return CapabilityImplementation(
            id=self.id,
            capability_id=self.capability_id,
            source=self.source,
            name=self.name,
            description=self.description,
            version=self.version,
            metadata=self.metadata,
            status=self.status,
            security_status=self.security_status,
            experience_score=new_experience,
            reliability_score=new_reliability,
            avg_latency_ms=self.avg_latency_ms,
            avg_cost=self.avg_cost,
            created_at=self.created_at,
            updated_at=now,
            last_used_at=now,
            usage_count=new_usage,
            success_count=self.success_count,
            failure_count=new_failure,
            error=error,
        )

    @classmethod
    def create(
        cls,
        capability_id: str,
        source: ImplementationSource,
        name: str,
        description: str,
        version: str,
        metadata: ImplementationMetadata,
    ) -> "CapabilityImplementation":
        """Create a new implementation."""
        impl_id = f"impl_{uuid4().hex[:16]}"
        now = datetime.now(UTC)
        return cls(
            id=impl_id,
            capability_id=capability_id,
            source=source,
            name=name,
            description=description,
            version=version,
            metadata=metadata,
            status=ImplementationStatus.REGISTERED,
            created_at=now,
            updated_at=now,
        )


def generate_implementation_id() -> str:
    """Generate a unique implementation ID."""
    return f"impl_{uuid4().hex[:16]}"