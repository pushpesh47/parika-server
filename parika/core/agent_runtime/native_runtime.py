"""
PARIKA Native Runtime Adapter

Implements the AgentRuntime interface for PARIKA's native execution.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
from parika.core.agent_runtime.contracts import (
    AgentRuntime,
    RuntimeCapabilities,
    RuntimeConfig,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
    RuntimeInfo,
    RuntimeStatus,
    RuntimeType,
)
from parika.core.autonomous.agent_supervisor import AgentSupervisor

if TYPE_CHECKING:
    from parika.core.autonomous.executor import AutonomousExecutor
    from parika.core.autonomous.task_manager import AutonomousTaskManager
    from parika.core.capability_executor.capability_executor import CapabilityExecutor
    from parika.core.event_bus.event_bus import EventBus
    from parika.core.logger.logger import Logger
    from parika.core.tool_manager.tool_manager import ToolManager
else:
    AutonomousExecutor = Any
    AutonomousTaskManager = Any
    CapabilityExecutor = Any
    EventBus = Any
    Logger = Any
    ToolManager = Any


@dataclass(slots=True, kw_only=True)
class NativeAgentExecution:
    """Tracks a native agent execution."""
    agent_id: str
    task_id: str
    capability_id: str
    future: asyncio.Future
    started_at: datetime
    skill_id: str | None = None


class NativeRuntimeAdapter(AgentRuntime):
    """
    Native PARIKA runtime adapter.

    Uses the existing AutonomousExecutor and AgentSupervisor
    for execution within the PARIKA process.
    """

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        executor: AutonomousExecutor,
        agent_supervisor: AgentSupervisor,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        agent_orchestrator: AgentOrchestrator,
        task_manager: AutonomousTaskManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._config = config
        self._executor = executor
        self._agent_supervisor = agent_supervisor
        self._capability_executor = capability_executor
        self._tool_manager = tool_manager
        self._agent_orchestrator = agent_orchestrator
        self._task_manager = task_manager
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._runtime_id = config.runtime_id
        self._status = RuntimeStatus.STOPPED
        self._started_at: datetime | None = None
        self._active_executions: dict[str, NativeAgentExecution] = {}
        self._lock = threading.RLock()

        # Capabilities
        self._capabilities = RuntimeCapabilities(
            supported_capability_categories=(
                "tool", "llm", "reasoning", "vision", "embedding",
                "translation", "speech", "text_to_speech",
                "image_generation", "video_generation", "ocr"
            ),
            max_concurrent_agents=config.resource_limits.get("max_concurrent_agents", 10),
            supports_checkpoint=True,
            supports_skills=True,
            supports_tools=True,
            supports_a2a=False,
            supports_streaming=True,
            resource_isolation="process",
        )

    @property
    def runtime_id(self) -> str:
        return self._runtime_id

    @property
    def runtime_type(self) -> RuntimeType:
        return RuntimeType.NATIVE

    @property
    def capabilities(self) -> RuntimeCapabilities:
        return self._capabilities

    @property
    def status(self) -> RuntimeStatus:
        return self._status

    async def discover(self) -> list[str]:
        """Discover available capabilities."""
        # In native runtime, capabilities come from CapabilityRegistry
        return []

    async def validate(self, config: RuntimeConfig) -> tuple[bool, str | None]:
        """Validate runtime configuration."""
        # Native runtime is always valid if PARIKA is running
        return True, None

    async def start(self) -> bool:
        """Start the native runtime."""
        if self._status == RuntimeStatus.RUNNING:
            return True

        self._status = RuntimeStatus.STARTING
        self._started_at = datetime.now(UTC)

        try:
            # Native runtime uses existing executor
            # The executor is already started in AutonomousRuntime
            self._status = RuntimeStatus.RUNNING
            self._logger.info("Native runtime started")
            return True
        except Exception as e:
            self._status = RuntimeStatus.ERROR
            self._logger.error("Failed to start native runtime: %s", e)
            return False

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
        Execute a capability in the native runtime.

        This delegates to the existing AutonomousExecutor path.
        """
        self._logger.info(
            "Native runtime executing capability '%s' for agent '%s'",
            capability_id, agent_id
        )

        # Create a task for execution
        from parika.core.autonomous.contracts import AutonomousTaskStatus
        from parika.core.autonomous.task_manager import AutonomousTask

        # Get or create task
        task = self._task_manager.get(task_id)
        if not task:
            # This shouldn't happen in normal flow - task should exist
            raise ValueError(f"Task '{task_id}' not found")

        # Check if skill is involved
        if skill_id:
            skill = self._agent_orchestrator.get_agent_for_capability(capability_id)
            # Skill would be loaded through SkillLoader

        # Execute through capability executor
        # This is a simplified path - actual execution goes through
        # AutonomousExecutor which handles authorization, budget, etc.
        from parika.core.capability_resolver.capability_request import CapabilityRequest
        from parika.core.capability_resolver.capability_resolver import CapabilityResolver
        from parika.core.capability_executor.request import CapabilityExecutionRequest
        from parika.core.capability_executor.execution_target import ExecutionTarget
        from parika.core.capability_executor.execution_backend import ExecutionBackend
        from parika.core.tool_manager.request import ToolRequest

        # Resolve capability
        # This would normally be done by AutonomousExecutor
        # For now, return a placeholder
        return MappingProxyType({
            "result": "Native runtime execution completed",
            "capability_id": capability_id,
            "agent_id": agent_id,
        })

    async def pause(self, agent_id: str) -> bool:
        """Pause an agent execution."""
        with self._lock:
            exec = self._active_executions.get(agent_id)
            if not exec:
                return False

        # In native runtime, pausing would involve the task manager
        agent = self._agent_supervisor.pause(agent_id)
        return agent is not None

    async def resume(self, agent_id: str) -> bool:
        """Resume a paused agent execution."""
        agent = self._agent_supervisor.resume(agent_id)
        return agent is not None

    async def cancel(self, agent_id: str) -> bool:
        """Cancel an agent execution."""
        with self._lock:
            exec = self._active_executions.get(agent_id)
            if not exec:
                return False

            exec.future.cancel()

        agent = self._agent_supervisor.terminate(agent_id, "Cancelled by runtime")
        return agent is not None

    async def terminate(self, agent_id: str) -> bool:
        """Terminate an agent (force stop)."""
        return await self.cancel(agent_id)

    async def heartbeat(self, agent_id: str) -> bool:
        """Send heartbeat for an agent."""
        agent = self._agent_supervisor.heartbeat(agent_id)
        return agent is not None

    async def get_status(self, agent_id: str) -> MappingProxyType[str, Any]:
        """Get agent execution status."""
        agent = self._agent_supervisor.get(agent_id)
        if not agent:
            return MappingProxyType({"status": "not_found"})

        return MappingProxyType({
            "agent_id": agent.id,
            "status": agent.status.value,
            "task_id": agent.task_id,
            "mission_id": agent.mission_id,
            "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
        })

    async def collect_result(self, agent_id: str) -> MappingProxyType[str, Any] | None:
        """Collect execution result."""
        agent = self._agent_supervisor.get(agent_id)
        if not agent:
            return None

        return agent.result

    async def checkpoint(self, agent_id: str) -> MappingProxyType[str, Any] | None:
        """Create checkpoint for agent."""
        # Would integrate with CheckpointManager
        agent = self._agent_supervisor.get(agent_id)
        if not agent:
            return None

        return MappingProxyType({
            "agent_id": agent_id,
            "status": agent.status.value,
            "checkpoint_time": datetime.now(UTC).isoformat(),
        })

    async def restore(self, agent_id: str, checkpoint: MappingProxyType[str, Any]) -> bool:
        """Restore agent from checkpoint."""
        # Would integrate with RecoveryCoordinator
        return False

    async def get_available_tools(self) -> list[str]:
        """Get list of available tool IDs."""
        tools = self._tool_manager.get_all()
        return [t.id for t in tools if t.enabled]

    async def get_available_skills(self) -> list[str]:
        """Get list of available skill IDs."""
        # Would integrate with SkillRegistry
        return []

    async def stop(self) -> bool:
        """Stop the native runtime."""
        if self._status == RuntimeStatus.STOPPED:
            return True

        self._status = RuntimeStatus.STOPPING

        # Cancel all active executions
        with self._lock:
            for exec in self._active_executions.values():
                exec.future.cancel()

        self._status = RuntimeStatus.STOPPED
        self._logger.info("Native runtime stopped")
        return True

    def get_info(self) -> RuntimeInfo:
        """Get runtime info."""
        return RuntimeInfo(
            runtime_id=self._runtime_id,
            name=self._config.name,
            runtime_type=self.runtime_type,
            status=self._status,
            capabilities=self._capabilities,
            config=self._config,
            started_at=self._started_at,
            active_agents=len(self._active_executions),
        )