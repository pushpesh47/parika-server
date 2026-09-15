"""
PARIKA Autonomous Execution - Execution Strategy Contracts

Defines the execution strategy and backend abstraction for autonomous tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ExecutionBackend(StrEnum):
    """Execution backend types for capability execution."""
    TOOL = "tool"              # PARIKA ToolManager execution
    PROVIDER = "provider"      # PARIKA ProviderManager + Planner execution
    HERMES = "hermes"          # Hermes subprocess execution
    REMOTE = "remote"          # Remote execution (future)


class RuntimeType(StrEnum):
    """Execution environment types."""
    NATIVE = "native"          # In-process PARIKA execution
    HERMES = "hermes"          # Hermes subprocess
    CONTAINER = "container"    # Containerized execution (future)
    REMOTE = "remote"          # Remote execution (future)
    GPU_WORKER = "gpu_worker"  # GPU worker (future)
    SANDBOXED = "sandboxed"    # Sandboxed execution (future)
    EXTERNAL_AGENT = "external_agent"  # External agent (future)


@dataclass(frozen=True, slots=True, kw_only=True)
class FallbackPolicy:
    """Per-capability fallback policy defining safe fallback conditions."""
    on_selection_failure: str = "auto"           # "auto" | "manual" | "never"
    on_environment_unavailable: str = "auto"     # "auto" | "manual" | "never"
    on_worker_unavailable: str = "auto"          # "auto" | "manual" | "never"
    on_timeout: str = "policy"                   # "auto" | "policy" | "never"
    on_transient_failure: str = "policy"         # "auto" | "policy" | "never"
    on_mutation: str = "never"                   # Hard-coded for mutation capabilities
    
    def is_auto_fallback_allowed(self, failure_class: str) -> bool:
        """Check if automatic fallback is allowed for a failure class."""
        policy_map = {
            "selection_failure": self.on_selection_failure,
            "environment_unavailable": self.on_environment_unavailable,
            "worker_unavailable": self.on_worker_unavailable,
            "timeout": self.on_timeout,
            "transient_failure": self.on_transient_failure,
            "mutation": self.on_mutation,
        }
        policy = policy_map.get(failure_class, "never")
        return policy == "auto"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStrategy:
    """
    Derived per-execution decision object for a single capability execution step.
    
    Contains all information needed to execute and audit one step.
    """
    # Implementation identity
    implementation_id: str
    implementation_version: str
    implementation_source: str
    capability_id: str
    
    # Execution mapping
    backend: ExecutionBackend
    required_environment: RuntimeType
    
    # Authorization and budget
    policy_decision_id: str | None = None
    budget_allocation_id: str | None = None
    
    # Fallback information
    fallback_from_execution_id: str | None = None
    fallback_reason: str | None = None
    fallback_chain: tuple[str, ...] = ()  # Implementation IDs in fallback order
    
    # Step context (for multi-step tasks)
    step_index: int = 0
    total_steps: int = 1
    
    # Execution metadata
    resolved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: MappingProxyType[str, Any] = MappingProxyType({})
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence/logging."""
        return {
            "implementation_id": self.implementation_id,
            "implementation_version": self.implementation_version,
            "implementation_source": self.implementation_source,
            "capability_id": self.capability_id,
            "backend": self.backend.value,
            "required_environment": self.required_environment.value,
            "policy_decision_id": self.policy_decision_id,
            "budget_allocation_id": self.budget_allocation_id,
            "fallback_from_execution_id": self.fallback_from_execution_id,
            "fallback_reason": self.fallback_reason,
            "fallback_chain": list(self.fallback_chain),
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "resolved_at": self.resolved_at.isoformat(),
            "metadata": dict(self.metadata),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionStrategy":
        """Create from dictionary."""
        return cls(
            implementation_id=data["implementation_id"],
            implementation_version=data["implementation_version"],
            implementation_source=data["implementation_source"],
            capability_id=data["capability_id"],
            backend=ExecutionBackend(data["backend"]),
            required_environment=RuntimeType(data["required_environment"]),
            policy_decision_id=data.get("policy_decision_id"),
            budget_allocation_id=data.get("budget_allocation_id"),
            fallback_from_execution_id=data.get("fallback_from_execution_id"),
            fallback_reason=data.get("fallback_reason"),
            fallback_chain=tuple(data.get("fallback_chain", ())),
            step_index=data.get("step_index", 0),
            total_steps=data.get("total_steps", 1),
            resolved_at=datetime.fromisoformat(data["resolved_at"]) if "resolved_at" in data else datetime.now(UTC),
            metadata=MappingProxyType(data.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAttemptRecord:
    """
    Immutable record of an execution attempt for audit and recovery.
    
    Persisted to ExecutionModel.
    """
    execution_id: str
    task_id: str
    worker_id: str
    agent_id: str
    attempt_number: int
    
    # Implementation details
    selected_implementation_id: str
    implementation_version: str
    implementation_source: str
    
    # Execution details
    execution_backend: ExecutionBackend
    required_environment: RuntimeType
    actual_environment: RuntimeType
    
    # Authorization and budget
    policy_decision_id: str | None = None
    budget_allocation_id: str | None = None
    
    # Fallback tracking
    fallback_from_execution_id: str | None = None
    fallback_reason: str | None = None
    
    # Step context
    step_index: int = 0
    
    # Timing and result
    status: str = "created"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    result: MappingProxyType[str, Any] | None = None
    error: str | None = None
    
    # Checkpoint relationship
    checkpoint_id: str | None = None
    
    # Metadata
    execution_metadata: MappingProxyType[str, Any] = MappingProxyType({})
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "agent_id": self.agent_id,
            "attempt_number": self.attempt_number,
            "selected_implementation_id": self.selected_implementation_id,
            "implementation_version": self.implementation_version,
            "implementation_source": self.implementation_source,
            "execution_backend": self.execution_backend.value,
            "required_environment": self.required_environment.value,
            "actual_environment": self.actual_environment.value,
            "policy_decision_id": self.policy_decision_id,
            "budget_allocation_id": self.budget_allocation_id,
            "fallback_from_execution_id": self.fallback_from_execution_id,
            "fallback_reason": self.fallback_reason,
            "step_index": self.step_index,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": dict(self.result) if self.result else None,
            "error": self.error,
            "checkpoint_id": self.checkpoint_id,
            "execution_metadata": dict(self.execution_metadata),
        }