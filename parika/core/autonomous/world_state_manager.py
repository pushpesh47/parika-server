"""
PARIKA Autonomous Execution - World State Manager

Maintains global operational state of autonomous execution.
Reconstructable from authoritative persistent state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.models import WorldStateModel
from parika.core.autonomous.repository import (
    MissionRepository,
    AutonomousTaskRepository,
    AgentInstanceRepository,
    WorkerRepository,
    WorldStateRepository,
)
# Phase 2 - AgentMessageRepository (lazy import to avoid circular dependency)
try:
    from parika.core.agent_communication.message_repository import AgentMessageRepository
except ImportError:
    AgentMessageRepository = None

from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.agent_runtime.runtime_registry import RuntimeRegistry
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class WorldState:
    """Global autonomous activity state snapshot."""
    active_missions: int
    active_tasks: int
    active_agents: int
    waiting_tasks: int
    blocked_tasks: int
    failed_tasks: int
    retrying_tasks: int
    scheduled_tasks: int
    pending_approvals: int
    active_workers: int
    crashed_workers: int
    resource_usage: MappingProxyType[str, Any]
    last_updated: datetime

    # Phase 2 extensions
    active_skills: int = 0
    active_agent_messages: int = 0
    pending_agent_messages: int = 0
    active_runtimes: int = 0
    runtime_health: MappingProxyType[str, Any] = MappingProxyType({})
    active_wait_conditions: int = 0
    multi_agent_missions: int = 0

    @classmethod
    def from_model(cls, model: WorldStateModel) -> "WorldState":
        return cls(
            active_missions=model.active_missions,
            active_tasks=model.active_tasks,
            active_agents=model.active_agents,
            waiting_tasks=model.waiting_tasks,
            blocked_tasks=model.blocked_tasks,
            failed_tasks=model.failed_tasks,
            retrying_tasks=model.retrying_tasks,
            scheduled_tasks=model.scheduled_tasks,
            pending_approvals=model.pending_approvals,
            active_workers=model.active_workers,
            crashed_workers=model.crashed_workers,
            resource_usage=MappingProxyType(model.resource_usage),
            last_updated=model.updated_at,
            active_skills=getattr(model, 'active_skills', 0),
            active_agent_messages=getattr(model, 'active_agent_messages', 0),
            pending_agent_messages=getattr(model, 'pending_agent_messages', 0),
            active_runtimes=getattr(model, 'active_runtimes', 0),
            runtime_health=MappingProxyType(getattr(model, 'runtime_health', {})),
            active_wait_conditions=getattr(model, 'active_wait_conditions', 0),
            multi_agent_missions=getattr(model, 'multi_agent_missions', 0),
        )

    def to_model(self) -> WorldStateModel:
        return WorldStateModel(
            active_missions=self.active_missions,
            active_tasks=self.active_tasks,
            active_agents=self.active_agents,
            waiting_tasks=self.waiting_tasks,
            blocked_tasks=self.blocked_tasks,
            failed_tasks=self.failed_tasks,
            retrying_tasks=self.retrying_tasks,
            scheduled_tasks=self.scheduled_tasks,
            pending_approvals=self.pending_approvals,
            active_workers=self.active_workers,
            crashed_workers=self.crashed_workers,
            resource_usage=dict(self.resource_usage),
            updated_at=self.last_updated,
        )


class WorldStateManager:
    """
    Maintains global operational state of autonomous execution.
    
    This is NOT a memory system - it's operational state reconstructed
    from authoritative persistent state.
    """

    def __init__(
        self,
        *,
        mission_repository: MissionRepository,
        task_repository: AutonomousTaskRepository,
        agent_repository: AgentInstanceRepository,
        worker_repository: WorkerRepository,
        world_state_repository: WorldStateRepository,
        message_repository: AgentMessageRepository | None = None,
        skill_registry: SkillRegistry | None = None,
        runtime_registry: RuntimeRegistry | None = None,
        logger: Logger,
    ) -> None:
        self._mission_repository = mission_repository
        self._task_repository = task_repository
        self._agent_repository = agent_repository
        self._worker_repository = worker_repository
        self._world_state_repository = world_state_repository
        self._message_repository = message_repository
        self._skill_registry = skill_registry
        self._runtime_registry = runtime_registry
        self._wait_manager = None  # Will be set later if needed
        self._logger = logger.get_logger(__name__)

    def build_snapshot(self) -> WorldState:
        """Build a world state snapshot from persistent state."""
        # Count missions by status
        active_mission_statuses = [
            "created", "planning", "running", "waiting", "paused", "blocked", "needs_approval"
        ]
        active_missions = sum(
            self._mission_repository.count_by_status(status) 
            for status in active_mission_statuses
        )

        # Count tasks by status
        active_task_statuses = [
            "created", "scheduled", "running", "waiting_for_dependency",
            "waiting_for_resource", "waiting_for_approval", "ready",
            "paused", "blocked"
        ]
        active_tasks = sum(
            self._task_repository.count_by_status(status) 
            for status in active_task_statuses
        )

        waiting_tasks = self._task_repository.count_by_status("waiting_for_dependency")
        blocked_tasks = self._task_repository.count_by_status("blocked")
        failed_tasks = self._task_repository.count_by_status("failed")
        retrying_tasks = self._task_repository.count_by_status("retrying")
        scheduled_tasks = self._task_repository.count_by_status("scheduled")

        # Count agents
        active_agent_statuses = ["spawned", "starting", "running", "waiting", "paused"]
        active_agents = sum(
            len(self._agent_repository.list_by_status(status)) 
            for status in active_agent_statuses
            if hasattr(self._agent_repository, 'list_by_status')
        )

        # Count workers
        active_worker_statuses = ["spawned", "starting", "running", "pausing", "paused", "resuming"]
        active_workers = sum(
            len(self._worker_repository.list_by_status(status))
            for status in active_worker_statuses
        )

        crashed_workers = len(self._worker_repository.list_crashed(120.0))

        # Get resource usage
        resource_usage = MappingProxyType({
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "disk_percent": 0.0,
        })

        # Phase 2 extensions
        active_skills = 0
        if self._skill_registry:
            stats = self._skill_registry.get_stats()
            active_skills = stats.get("by_status", {}).get("active", 0)

        active_agent_messages = 0
        pending_agent_messages = 0
        if self._message_repository:
            active_agent_messages = self._message_repository.count_by_status("processed")
            pending_agent_messages = (
                self._message_repository.count_by_status("sent") +
                self._message_repository.count_by_status("delivered")
            )

        active_runtimes = 0
        runtime_health = MappingProxyType({})
        if self._runtime_registry:
            stats = self._runtime_registry.get_stats()
            active_runtimes = stats.get("by_status", {}).get("running", 0)
            for rt_info in self._runtime_registry.list_runtimes():
                runtime_health = runtime_health.copy()
                runtime_health[rt_info.runtime_id] = {
                    "status": rt_info.status.value,
                    "active_agents": rt_info.active_agents,
                }

        active_wait_conditions = 0
        if self._wait_manager:
            wait_stats = self._wait_manager.get_stats()
            active_wait_conditions = wait_stats.get("waiting", 0)

        multi_agent_missions = 0  # Would need mission coordination tracking

        snapshot = WorldState(
            active_missions=active_missions,
            active_tasks=active_tasks,
            active_agents=active_agents,
            waiting_tasks=waiting_tasks,
            blocked_tasks=blocked_tasks,
            failed_tasks=failed_tasks,
            retrying_tasks=retrying_tasks,
            scheduled_tasks=scheduled_tasks,
            pending_approvals=0,
            active_workers=active_workers,
            crashed_workers=crashed_workers,
            resource_usage=resource_usage,
            last_updated=datetime.now(UTC),
            active_skills=active_skills,
            active_agent_messages=active_agent_messages,
            pending_agent_messages=pending_agent_messages,
            active_runtimes=active_runtimes,
            runtime_health=runtime_health,
            active_wait_conditions=active_wait_conditions,
            multi_agent_missions=multi_agent_missions,
        )

        return snapshot

    def persist_snapshot(self, snapshot: WorldState) -> WorldStateModel:
        """Persist a world state snapshot."""
        model = snapshot.to_model()
        return self._world_state_repository.create_snapshot(model)

    def get_latest_snapshot(self) -> WorldState | None:
        """Get the latest persisted world state snapshot."""
        model = self._world_state_repository.get_latest()
        return WorldState.from_model(model) if model else None

    def update_from_persistent(self) -> WorldState:
        """Update and persist world state from current persistent state."""
        snapshot = self.build_snapshot()
        self.persist_snapshot(snapshot)
        return snapshot