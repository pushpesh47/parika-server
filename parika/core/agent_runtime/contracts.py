"""
PARIKA Agent Runtime Contracts

Defines the abstract contract for agent runtimes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class RuntimeType(StrEnum):
    """Supported runtime types."""
    NATIVE = "native"
    HERMES = "hermes"
    REMOTE = "remote"


class RuntimeStatus(StrEnum):
    """Runtime lifecycle status."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeCapabilities:
    """Capabilities provided by a runtime."""
    supported_capability_categories: tuple[str, ...] = ()
    max_concurrent_agents: int = 10
    supports_checkpoint: bool = True
    supports_skills: bool = True
    supports_tools: bool = True
    supports_a2a: bool = False
    supports_streaming: bool = False
    resource_isolation: str = "process"  # "none", "process", "container", "vm"


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeConfig:
    """Configuration for a runtime instance."""
    runtime_type: RuntimeType
    runtime_id: str
    name: str
    config: MappingProxyType[str, Any] = MappingProxyType({})
    resource_limits: MappingProxyType[str, Any] = MappingProxyType({})
    environment: MappingProxyType[str, str] = MappingProxyType({})
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_type": self.runtime_type.value,
            "runtime_id": self.runtime_id,
            "name": self.name,
            "config": dict(self.config),
            "resource_limits": dict(self.resource_limits),
            "environment": dict(self.environment),
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeInfo:
    """Runtime information."""
    runtime_id: str
    name: str
    runtime_type: RuntimeType
    status: RuntimeStatus
    capabilities: RuntimeCapabilities
    config: RuntimeConfig
    started_at: datetime | None = None
    last_heartbeat: datetime | None = None
    active_agents: int = 0
    error: str | None = None


class AgentRuntime(ABC):
    """
    Abstract base class for agent runtimes.

    All runtimes must implement this interface to be compatible
    with PARIKA's autonomous execution system.
    """

    @property
    @abstractmethod
    def runtime_id(self) -> str:
        """Unique runtime identifier."""
        pass

    @property
    @abstractmethod
    def runtime_type(self) -> RuntimeType:
        """Runtime type."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> RuntimeCapabilities:
        """Runtime capabilities."""
        pass

    @property
    @abstractmethod
    def status(self) -> RuntimeStatus:
        """Current runtime status."""
        pass

    @abstractmethod
    async def discover(self) -> list[str]:
        """
        Discover available capabilities/skills in this runtime.

        Returns:
            List of capability/skill identifiers available
        """
        pass

    @abstractmethod
    async def validate(self, config: RuntimeConfig) -> tuple[bool, str | None]:
        """
        Validate runtime configuration.

        Returns:
            Tuple of (is_valid, error_message)
        """
        pass

    @abstractmethod
    async def start(self) -> bool:
        """
        Start the runtime.

        Returns:
            True if started successfully
        """
        pass

    @abstractmethod
    async def execute(
        self,
        agent_id: str,
        task_id: str,
        capability_id: str,
        inputs: MappingProxyType[str, Any],
        context: MappingProxyType[str, Any],
        skill_id: str | None = None,
    ) -> MappingProxyType[str, Any]:
        """
        Execute a capability in this runtime.

        Args:
            agent_id: Agent instance ID
            task_id: Task ID
            capability_id: Capability to execute
            inputs: Input parameters
            context: Execution context (permissions, budget, etc.)
            skill_id: Optional skill to use

        Returns:
            Execution result
        """
        pass

    @abstractmethod
    async def pause(self, agent_id: str) -> bool:
        """Pause an agent execution."""
        pass

    @abstractmethod
    async def resume(self, agent_id: str) -> bool:
        """Resume a paused agent execution."""
        pass

    @abstractmethod
    async def cancel(self, agent_id: str) -> bool:
        """Cancel an agent execution."""
        pass

    @abstractmethod
    async def terminate(self, agent_id: str) -> bool:
        """Terminate an agent (force stop)."""
        pass

    @abstractmethod
    async def heartbeat(self, agent_id: str) -> bool:
        """Send heartbeat for an agent."""
        pass

    @abstractmethod
    async def get_status(self, agent_id: str) -> MappingProxyType[str, Any]:
        """Get agent execution status."""
        pass

    @abstractmethod
    async def collect_result(self, agent_id: str) -> MappingProxyType[str, Any] | None:
        """Collect execution result."""
        pass

    @abstractmethod
    async def checkpoint(self, agent_id: str) -> MappingProxyType[str, Any] | None:
        """Create checkpoint for agent."""
        pass

    @abstractmethod
    async def restore(self, agent_id: str, checkpoint: MappingProxyType[str, Any]) -> bool:
        """Restore agent from checkpoint."""
        pass

    @abstractmethod
    async def get_available_tools(self) -> list[str]:
        """Get list of available tool IDs."""
        pass

    @abstractmethod
    async def get_available_skills(self) -> list[str]:
        """Get list of available skill IDs."""
        pass

    @abstractmethod
    async def stop(self) -> bool:
        """Stop the runtime."""
        pass


@dataclass(slots=True, kw_only=True)
class RuntimeExecutionRequest:
    """Request to execute in a runtime."""
    agent_id: str
    task_id: str
    capability_id: str
    inputs: MappingProxyType[str, Any]
    context: MappingProxyType[str, Any]
    skill_id: str | None = None
    implementation_id: str | None = None
    timeout_seconds: float = 300.0


@dataclass(slots=True, kw_only=True)
class RuntimeExecutionResult:
    """Result of runtime execution."""
    success: bool
    result: MappingProxyType[str, Any] | None = None
    error: str | None = None
    execution_time_ms: float = 0.0
    checkpoint: MappingProxyType[str, Any] | None = None
    metadata: MappingProxyType[str, Any] = MappingProxyType({})