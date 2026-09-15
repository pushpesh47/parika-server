"""
PARIKA Mission Coordinator

Coordinates multi-agent mission execution with task delegation and dependency management.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.mission_manager import MissionManager
from parika.core.autonomous.task_manager import AutonomousTaskManager
from parika.core.autonomous.agent_supervisor import AgentSupervisor
from parika.core.autonomous.contracts import MissionStatus, AutonomousTaskStatus
from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
from parika.core.agent_communication.message_bus import MessageBus
from parika.core.agent_communication.message import AgentMessage, MessageType, MessagePriority
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.skill_system.skill_loader import SkillLoader
from parika.core.skill_system.skill_catalog import SkillCatalog


@dataclass(slots=True, kw_only=True)
class AgentAssignment:
    """Assignment of an agent to a task."""
    agent_id: str
    task_id: str
    agent_profile_id: str
    capability_id: str
    skill_id: str | None = None


@dataclass(slots=True, kw_only=True)
class MissionExecutionPlan:
    """Execution plan for a mission with multiple agents."""
    mission_id: str
    agent_assignments: list[AgentAssignment]
    task_dependencies: dict[str, list[str]]  # task_id -> [dependency_task_ids]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MissionCoordinator:
    """
    Coordinates multi-agent mission execution.

    Responsibilities:
    - Plan mission execution with multiple agents
    - Spawn and manage agent instances
    - Handle task dependencies and coordination
    - Manage inter-agent communication
    - Track mission progress
    """

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
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._mission_manager = mission_manager
        self._task_manager = task_manager
        self._agent_supervisor = agent_supervisor
        self._agent_orchestrator = agent_orchestrator
        self._message_bus = message_bus
        self._skill_loader = skill_loader
        self._skill_catalog = skill_catalog
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        # Active mission plans
        self._mission_plans: dict[str, MissionExecutionPlan] = {}
        # Agent assignments by mission
        self._mission_agents: dict[str, dict[str, AgentAssignment]] = {}

    def plan_mission(
        self,
        mission_id: str,
        tasks: list[dict[str, Any]],
    ) -> MissionExecutionPlan:
        """
        Plan a mission with multiple tasks and agent assignments.

        Args:
            mission_id: Mission to plan
            tasks: List of task definitions with:
                - name, description
                - capability_id
                - agent_profile_id (optional)
                - skill_id (optional)
                - depends_on (optional list of task names/ids)
                - inputs
                - metadata (optional, can include execution_plan)

        Returns:
            MissionExecutionPlan with agent assignments
        """
        mission = self._mission_manager.get(mission_id)
        if not mission:
            raise ValueError(f"Mission '{mission_id}' not found")

        # Create tasks and assign agents
        agent_assignments = []
        task_id_map = {}  # name -> task_id
        task_dependencies = {}

        for task_def in tasks:
            # Determine agent profile
            agent_profile_id = task_def.get("agent_profile_id") or "agent.general"
            skill_id = task_def.get("skill_id")

            # Create the task
            task = self._task_manager.create(
                mission_id=mission_id,
                name=task_def["name"],
                description=task_def.get("description", ""),
                capability_id=task_def["capability_id"],
                inputs=task_def.get("inputs", MappingProxyType({})),
                metadata=task_def.get("metadata", MappingProxyType({})),
            )

            task_id_map[task_def["name"]] = task.id

            # Handle dependencies
            depends_on = task_def.get("depends_on", [])
            dep_ids = [task_id_map[name] for name in depends_on if name in task_id_map]
            task_dependencies[task.id] = dep_ids

            # For now, agent will be spawned when task is ready to execute
            # We record the assignment plan
            assignment = AgentAssignment(
                agent_id="",  # Will be filled when spawned
                task_id=task.id,
                agent_profile_id=agent_profile_id,
                capability_id=task_def["capability_id"],
                skill_id=skill_id,
            )
            agent_assignments.append(assignment)

        plan = MissionExecutionPlan(
            mission_id=mission_id,
            agent_assignments=agent_assignments,
            task_dependencies=task_dependencies,
        )

        self._mission_plans[mission_id] = plan
        self._mission_agents[mission_id] = {}

        self._logger.info(
            "Planned mission '%s' with %d tasks and %d agent assignments",
            mission_id, len(tasks), len(agent_assignments)
        )

        return plan

    async def execute_mission(self, mission_id: str) -> MissionExecutionPlan:
        """
        Execute a planned mission.

        Spawns agents and coordinates their execution based on dependencies.
        """
        plan = self._mission_plans.get(mission_id)
        if not plan:
            raise ValueError(f"No execution plan for mission '{mission_id}'")

        # Start mission
        self._mission_manager.start(mission_id)

        # Spawn agents for each assignment (on-demand when tasks are ready)
        # Agents are spawned by AutonomousExecutor when task is claimed
        self._logger.info("Started execution of mission '%s'", mission_id)

        return plan

    async def _spawn_agent_for_assignment(
        self,
        mission_id: str,
        assignment: AgentAssignment,
    ) -> str:
        """Spawn an agent for a task assignment (called at execution time)."""
        # Get the task
        task = self._task_manager.get(assignment.task_id)
        if not task:
            raise ValueError(f"Task '{assignment.task_id}' not found")

        # Spawn agent instance
        agent = self._agent_supervisor.spawn(
            mission_id=mission_id,
            task_id=assignment.task_id,
            agent_profile_id=assignment.agent_profile_id,
            skill_id=assignment.skill_id,
            metadata=MappingProxyType({
                "assignment_capability": assignment.capability_id,
                "assignment_skill": assignment.skill_id or "",
            }),
        )

        # Update assignment with agent ID
        assignment.agent_id = agent.id

        # Track assignment
        self._mission_agents[mission_id][assignment.task_id] = assignment

        self._logger.info(
            "Spawned agent '%s' for task '%s' (profile: %s, skill: %s)",
            agent.id, assignment.task_id, assignment.agent_profile_id, assignment.skill_id or "none"
        )

        return agent.id

    def get_mission_plan(self, mission_id: str) -> MissionExecutionPlan | None:
        """Get mission execution plan."""
        return self._mission_plans.get(mission_id)

    def get_agent_for_task(self, mission_id: str, task_id: str) -> AgentAssignment | None:
        """Get agent assignment for a task."""
        return self._mission_agents.get(mission_id, {}).get(task_id)

    def get_mission_agents(self, mission_id: str) -> list[AgentAssignment]:
        """Get all agent assignments for a mission."""
        return list(self._mission_agents.get(mission_id, {}).values())

    def send_agent_message(
        self,
        mission_id: str,
        from_task_id: str,
        to_task_id: str,
        message_type: MessageType,
        payload: MappingProxyType[str, Any],
        *,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> AgentMessage:
        """Send a message between agents in the same mission."""
        from_assignment = self._mission_agents.get(mission_id, {}).get(from_task_id)
        to_assignment = self._mission_agents.get(mission_id, {}).get(to_task_id)

        if not from_assignment or not to_assignment:
            raise ValueError("Invalid task IDs for message")

        if not from_assignment.agent_id or not to_assignment.agent_id:
            raise ValueError("Agents not yet spawned")

        return self._message_bus.send(
            sender_agent_id=from_assignment.agent_id,
            recipient_agent_id=to_assignment.agent_id,
            mission_id=mission_id,
            message_type=message_type,
            payload=payload,
            task_id=from_task_id,
            priority=priority,
        )

    def broadcast_mission_message(
        self,
        mission_id: str,
        from_task_id: str,
        message_type: MessageType,
        payload: MappingProxyType[str, Any],
        *,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> list[AgentMessage]:
        """Broadcast a message to all agents in a mission."""
        from_assignment = self._mission_agents.get(mission_id, {}).get(from_task_id)
        if not from_assignment or not from_assignment.agent_id:
            raise ValueError("From agent not spawned")

        messages = []
        for assignment in self._mission_agents.get(mission_id, {}).values():
            if assignment.task_id != from_task_id and assignment.agent_id:
                msg = self._message_bus.send(
                    sender_agent_id=from_assignment.agent_id,
                    recipient_agent_id=assignment.agent_id,
                    mission_id=mission_id,
                    message_type=message_type,
                    payload=payload,
                    task_id=from_task_id,
                    priority=priority,
                )
                messages.append(msg)

        return messages

    def complete_task(
        self,
        mission_id: str,
        task_id: str,
        result: MappingProxyType[str, Any] | None = None,
    ) -> None:
        """Complete a task and notify dependent tasks."""
        self._task_manager.complete(task_id, result)

        # Check if all tasks in mission are complete
        plan = self._mission_plans.get(mission_id)
        if plan:
            all_complete = True
            for assignment in plan.agent_assignments:
                task = self._task_manager.get(assignment.task_id)
                if task and task.status != AutonomousTaskStatus.COMPLETED:
                    all_complete = False
                    break

            if all_complete:
                self._mission_manager.complete(mission_id, result)
        
        # Publish agent message for task completion
        assignment = self._mission_agents.get(mission_id, {}).get(task_id)
        if assignment and assignment.agent_id:
            self._message_bus.send(
                sender_agent_id=assignment.agent_id,
                recipient_agent_id=None,  # Broadcast
                mission_id=mission_id,
                message_type=MessageType.TASK_RESULT,
                payload=dict(result) if result else {},
                task_id=task_id,
            )

    def fail_task(
        self,
        mission_id: str,
        task_id: str,
        failure: str,
    ) -> None:
        """Fail a task."""
        self._task_manager.fail(task_id, failure)

        # Could trigger mission failure or fallback logic here
        self._logger.error("Task '%s' in mission '%s' failed: %s", task_id, mission_id, failure)

    def get_mission_progress(self, mission_id: str) -> dict[str, Any]:
        """Get detailed mission progress."""
        plan = self._mission_plans.get(mission_id)
        mission = self._mission_manager.get(mission_id)

        if not plan or not mission:
            return {"error": "Mission not found"}

        tasks_info = []
        completed = 0
        failed = 0
        running = 0
        waiting = 0

        for assignment in plan.agent_assignments:
            task = self._task_manager.get(assignment.task_id)
            if task:
                tasks_info.append({
                    "task_id": task.id,
                    "name": task.name,
                    "status": task.status.value,
                    "progress": task.progress,
                    "agent_id": assignment.agent_id,
                    "agent_profile": assignment.agent_profile_id,
                    "capability": assignment.capability_id,
                    "skill": assignment.skill_id,
                })

                if task.status == AutonomousTaskStatus.COMPLETED:
                    completed += 1
                elif task.status == AutonomousTaskStatus.FAILED:
                    failed += 1
                elif task.status == AutonomousTaskStatus.RUNNING:
                    running += 1
                elif task.status in (
                    AutonomousTaskStatus.WAITING_FOR_DEPENDENCY,
                    AutonomousTaskStatus.WAITING_FOR_RESOURCE,
                    AutonomousTaskStatus.WAITING_FOR_APPROVAL,
                ):
                    waiting += 1

        return {
            "mission_id": mission_id,
            "mission_status": mission.status.value,
            "mission_progress": mission.progress,
            "total_tasks": len(plan.agent_assignments),
            "completed": completed,
            "failed": failed,
            "running": running,
            "waiting": waiting,
            "tasks": tasks_info,
        }