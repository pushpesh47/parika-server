"""
PARIKA Multi-Agent Coordinator

Main entry point for multi-agent coordination.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.mission_manager import MissionManager
from parika.core.autonomous.task_manager import AutonomousTaskManager
from parika.core.autonomous.agent_supervisor import AgentSupervisor
from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
from parika.core.agent_communication.message_bus import MessageBus
from parika.core.skill_system.skill_loader import SkillLoader
from parika.core.skill_system.skill_catalog import SkillCatalog
from parika.core.multi_agent.mission_coordinator import MissionCoordinator
from parika.core.multi_agent.agent_selector import AgentSelector
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class MultiAgentCoordinator:
    """
    Top-level coordinator for multi-agent autonomous execution.

    Integrates:
    - Mission planning and execution
    - Agent selection and spawning
    - Inter-agent communication
    - Skill activation
    - Runtime selection
    """

    mission_manager: MissionManager
    task_manager: AutonomousTaskManager
    agent_supervisor: AgentSupervisor
    agent_orchestrator: AgentOrchestrator
    message_bus: MessageBus
    skill_loader: SkillLoader
    skill_catalog: SkillCatalog
    mission_coordinator: MissionCoordinator
    agent_selector: AgentSelector
    event_bus: EventBus
    logger: Logger

    def __init__(
        self,
        *,
        mission_manager: MissionManager,
        task_manager: AutonomousTaskManager,
        agent_supervisor: AgentSupervisor,
        agent_orchestrator: AgentOrchestrator,
        message_bus: MessageBus,
        skill_loader: SkillLoader,
        skill_catalog: SkillCatalog,
        mission_coordinator: MissionCoordinator,
        agent_selector: AgentSelector,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self.mission_manager = mission_manager
        self.task_manager = task_manager
        self.agent_supervisor = agent_supervisor
        self.agent_orchestrator = agent_orchestrator
        self.message_bus = message_bus
        self.skill_loader = skill_loader
        self.skill_catalog = skill_catalog
        self.mission_coordinator = mission_coordinator
        self.agent_selector = agent_selector
        self.event_bus = event_bus
        self.logger = logger

    async def execute_multi_agent_mission(
        self,
        mission_id: str,
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Execute a mission with multiple agents.

        Args:
            mission_id: Mission to execute
            tasks: Task definitions

        Returns:
            Mission execution result
        """
        # Plan mission
        plan = self.mission_coordinator.plan_mission(mission_id, tasks)

        # Execute mission
        await self.mission_coordinator.execute_mission(mission_id)

        return {
            "mission_id": mission_id,
            "plan": plan,
            "status": "started",
        }

    def get_mission_status(self, mission_id: str) -> dict[str, Any]:
        """Get mission status with agent details."""
        return self.mission_coordinator.get_mission_progress(mission_id)

    def send_agent_message(
        self,
        mission_id: str,
        from_task_id: str,
        to_task_id: str,
        message_type: str,
        payload: MappingProxyType[str, Any],
    ) -> Any:
        """Send message between agents in a mission."""
        from parika.core.agent_communication.message import MessageType
        return self.mission_coordinator.send_agent_message(
            mission_id=mission_id,
            from_task_id=from_task_id,
            to_task_id=to_task_id,
            message_type=MessageType(message_type),
            payload=payload,
        )

    def broadcast_message(
        self,
        mission_id: str,
        from_task_id: str,
        message_type: str,
        payload: MappingProxyType[str, Any],
    ) -> list:
        """Broadcast message to all agents in mission."""
        from parika.core.agent_communication.message import MessageType
        return self.mission_coordinator.broadcast_mission_message(
            mission_id=mission_id,
            from_task_id=from_task_id,
            message_type=MessageType(message_type),
            payload=payload,
        )