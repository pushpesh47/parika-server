"""
PARIKA Autonomous Execution - Execution Backend Abstraction

Defines the interface for executing capabilities via different backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.execution_strategy import ExecutionStrategy


@dataclass(frozen=True, slots=True, kw_only=True)
class BackendExecutionContext:
    """Context passed to backend for execution."""
    task_id: str
    mission_id: str
    agent_id: str
    agent_profile_id: str
    permission_context: MappingProxyType[str, Any]
    resource_budget: MappingProxyType[str, Any]
    step_index: int = 0
    total_steps: int = 1
    previous_results: MappingProxyType[str, Any] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BackendExecutionResult:
    """Result from backend execution."""
    success: bool
    result: MappingProxyType[str, Any] | None = None
    error: str | None = None
    execution_time_ms: float = 0.0
    checkpoint: MappingProxyType[str, Any] | None = None
    metadata: MappingProxyType[str, Any] = MappingProxyType({})


class ExecutionBackend(ABC):
    """
    Abstract base class for execution backends.
    
    Each backend implements a specific execution mechanism:
    - TOOL: Direct tool execution via ToolManager
    - PROVIDER: LLM provider execution via Planner + CapabilityExecutor
    - HERMES: Hermes subprocess execution
    - REMOTE: Remote execution (future)
    """

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Backend type identifier."""
        pass

    @abstractmethod
    async def execute(
        self,
        strategy: ExecutionStrategy,
        inputs: MappingProxyType[str, Any],
        context: BackendExecutionContext,
    ) -> BackendExecutionResult:
        """
        Execute a capability using this backend.
        
        Args:
            strategy: Resolved execution strategy
            inputs: Capability inputs
            context: Execution context (permissions, budget, agent info, step info)
            
        Returns:
            BackendExecutionResult with success/error/result
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend is available for execution."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Perform health check on backend."""
        pass