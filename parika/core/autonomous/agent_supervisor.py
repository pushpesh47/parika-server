"""
PARIKA Autonomous Execution - Agent Supervisor

Tracks and supervises agent instances for autonomous execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.contracts import AgentInstanceStatus
from parika.core.autonomous.events import (
    AgentSpawnedEvent,
    AgentStartedEvent,
    AgentCompletedEvent,
    AgentFailedEvent,
)
from parika.core.autonomous.models import AgentInstanceModel
from parika.core.autonomous.repository import AgentInstanceRepository
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class AgentInstance:
    """Agent Instance domain model."""
    id: str
    mission_id: str
    task_id: str
    agent_profile_id: str
    parent_agent_id: str | None
    child_agent_ids: tuple[str, ...]
    status: AgentInstanceStatus
    runtime: str
    permission_context: MappingProxyType[str, Any]
    resource_budget: MappingProxyType[str, Any]
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    last_heartbeat: datetime | None
    result: MappingProxyType[str, Any] | None
    failure: str | None
    metadata: MappingProxyType[str, Any]

    @classmethod
    def from_model(cls, model: AgentInstanceModel) -> "AgentInstance":
        return cls(
            id=model.id,
            mission_id=model.mission_id,
            task_id=model.task_id,
            agent_profile_id=model.agent_profile_id,
            parent_agent_id=model.parent_agent_id,
            child_agent_ids=tuple(model.metadata.get("child_agent_ids", [])),
            status=AgentInstanceStatus(model.status),
            runtime=model.runtime,
            permission_context=MappingProxyType(model.permission_context),
            resource_budget=MappingProxyType(model.resource_budget),
            created_at=model.created_at,
            started_at=model.started_at,
            updated_at=model.updated_at,
            completed_at=model.completed_at,
            last_heartbeat=model.last_heartbeat,
            result=MappingProxyType(model.result) if model.result else None,
            failure=model.failure,
            metadata=MappingProxyType(model.metadata),
        )

    def to_model(self) -> AgentInstanceModel:
        metadata = dict(self.metadata)
        metadata["child_agent_ids"] = list(self.child_agent_ids)
        return AgentInstanceModel(
            id=self.id,
            mission_id=self.mission_id,
            task_id=self.task_id,
            agent_profile_id=self.agent_profile_id,
            parent_agent_id=self.parent_agent_id,
            status=self.status.value,
            runtime=self.runtime,
            permission_context=dict(self.permission_context),
            resource_budget=dict(self.resource_budget),
            created_at=self.created_at,
            started_at=self.started_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
            last_heartbeat=self.last_heartbeat,
            result=dict(self.result) if self.result else None,
            failure=self.failure,
            metadata=metadata,
        )


class AgentSupervisor:
    """
    Supervises agent instances for autonomous execution.
    
    Tracks agent lifecycle, parent-child relationships, heartbeats,
    and coordinates with AgentOrchestrator for agent resolution.
    """

    def __init__(
        self,
        *,
        repository: AgentInstanceRepository,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def spawn(
        self,
        mission_id: str,
        task_id: str,
        agent_profile_id: str,
        *,
        parent_agent_id: str | None = None,
        runtime: str = "native",
        permission_context: MappingProxyType[str, Any] | None = None,
        resource_budget: MappingProxyType[str, Any] | None = None,
        metadata: MappingProxyType[str, Any] | None = None,
    ) -> AgentInstance:
        """Spawn a new agent instance."""
        now = datetime.now(UTC)
        
        agent = AgentInstance(
            id=self._generate_id(),
            mission_id=mission_id,
            task_id=task_id,
            agent_profile_id=agent_profile_id,
            parent_agent_id=parent_agent_id,
            child_agent_ids=(),
            status=AgentInstanceStatus.SPAWNED,
            runtime=runtime,
            permission_context=permission_context or MappingProxyType({}),
            resource_budget=resource_budget or MappingProxyType({}),
            created_at=now,
            started_at=None,
            updated_at=now,
            completed_at=None,
            last_heartbeat=None,
            result=None,
            failure=None,
            metadata=metadata or MappingProxyType({}),
        )

        model = agent.to_model()
        self._repository.create(model)

        # If parent agent exists, update its child list
        if parent_agent_id:
            parent = self.get(parent_agent_id)
            if parent:
                parent.child_agent_ids = parent.child_agent_ids + (agent.id,)
                self._repository.update(parent.to_model())

        self._event_bus.publish("agent.spawned", AgentSpawnedEvent(
            event_id=self._generate_id(),
            mission_id=mission_id,
            task_id=task_id,
            agent_id=agent.id,
            agent_profile_id=agent_profile_id,
            runtime=runtime,
            permission_context=permission_context or MappingProxyType({}),
            resource_budget=resource_budget or MappingProxyType({}),
        ))

        self._logger.info("Spawned agent instance '%s' (profile: %s) for task '%s'", 
                         agent.id, agent_profile_id, task_id)
        return agent

    def start(self, agent_id: str) -> AgentInstance | None:
        """Start an agent instance (SPAWNED -> STARTING -> RUNNING)."""
        agent = self.get(agent_id)
        if agent is None:
            return None

        if agent.status != AgentInstanceStatus.SPAWNED:
            return None

        agent.status = AgentInstanceStatus.STARTING
        agent.updated_at = datetime.now(UTC)
        self._repository.update(agent.to_model())

        agent.status = AgentInstanceStatus.RUNNING
        agent.started_at = datetime.now(UTC)
        agent.updated_at = datetime.now(UTC)
        self._repository.update(agent.to_model())

        self._event_bus.publish("agent.started", AgentStartedEvent(
            event_id=self._generate_id(),
            mission_id=agent.mission_id,
            task_id=agent.task_id,
            agent_id=agent.id,
        ))

        self._logger.info("Started agent instance '%s'", agent_id)
        return agent

    def heartbeat(self, agent_id: str) -> AgentInstance | None:
        """Record agent heartbeat."""
        agent = self.get(agent_id)
        if agent is None:
            return None

        if agent.status != AgentInstanceStatus.RUNNING:
            return None

        agent.last_heartbeat = datetime.now(UTC)
        agent.updated_at = datetime.now(UTC)
        self._repository.update(agent.to_model())

        return agent

    def complete(self, agent_id: str, result: MappingProxyType[str, Any] | None = None) -> AgentInstance | None:
        """Mark agent instance as completed."""
        agent = self.get(agent_id)
        if agent is None:
            return None

        if agent.status != AgentInstanceStatus.RUNNING:
            return None

        agent.status = AgentInstanceStatus.COMPLETED
        agent.completed_at = datetime.now(UTC)
        agent.result = result
        agent.updated_at = datetime.now(UTC)
        self._repository.update(agent.to_model())

        self._event_bus.publish("agent.completed", AgentCompletedEvent(
            event_id=self._generate_id(),
            mission_id=agent.mission_id,
            task_id=agent.task_id,
            agent_id=agent.id,
            result=result,
        ))

        self._logger.info("Agent instance '%s' completed", agent_id)
        return agent

    def fail(self, agent_id: str, failure: str) -> AgentInstance | None:
        """Mark agent instance as failed."""
        agent = self.get(agent_id)
        if agent is None:
            return None

        if agent.status != AgentInstanceStatus.RUNNING:
            return None

        agent.status = AgentInstanceStatus.FAILED
        agent.failure = failure
        agent.completed_at = datetime.now(UTC)
        agent.updated_at = datetime.now(UTC)
        self._repository.update(agent.to_model())

        self._event_bus.publish("agent.failed", AgentFailedEvent(
            event_id=self._generate_id(),
            mission_id=agent.mission_id,
            task_id=agent.task_id,
            agent_id=agent.id,
            failure=failure,
        ))

        self._logger.error("Agent instance '%s' failed: %s", agent_id, failure)
        return agent

    def terminate(self, agent_id: str, reason: str | None = None) -> AgentInstance | None:
        """Terminate an agent instance."""
        agent = self.get(agent_id)
        if agent is None:
            return None

        if agent.status in (AgentInstanceStatus.COMPLETED, AgentInstanceStatus.FAILED, AgentInstanceStatus.TERMINATED):
            return None

        agent.status = AgentInstanceStatus.TERMINATED
        agent.failure = reason
        agent.completed_at = datetime.now(UTC)
        agent.updated_at = datetime.now(UTC)
        self._repository.update(agent.to_model())

        # Also terminate child agents
        for child_id in agent.child_agent_ids:
            self.terminate(child_id, f"Parent agent terminated: {reason}")

        self._logger.info("Terminated agent instance '%s': %s", agent_id, reason)
        return agent

    def pause(self, agent_id: str) -> AgentInstance | None:
        """Pause a running agent."""
        agent = self.get(agent_id)
        if agent is None:
            return None

        if agent.status != AgentInstanceStatus.RUNNING:
            return None

        agent.status = AgentInstanceStatus.PAUSED
        agent.updated_at = datetime.now(UTC)
        self._repository.update(agent.to_model())

        # Also pause child agents
        for child_id in agent.child_agent_ids:
            self.pause(child_id)

        return agent

    def resume(self, agent_id: str) -> AgentInstance | None:
        """Resume a paused agent."""
        agent = self.get(agent_id)
        if agent is None:
            return None

        if agent.status != AgentInstanceStatus.PAUSED:
            return None

        agent.status = AgentInstanceStatus.RUNNING
        agent.updated_at = datetime.now(UTC)
        self._repository.update(agent.to_model())

        # Also resume child agents
        for child_id in agent.child_agent_ids:
            self.resume(child_id)

        return agent

    def get(self, agent_id: str) -> AgentInstance | None:
        """Get an agent instance by ID."""
        model = self._repository.get(agent_id)
        return AgentInstance.from_model(model) if model else None

    def get_by_task(self, task_id: str) -> list[AgentInstance]:
        """Get all agent instances for a task."""
        models = self._repository.list_by_task(task_id)
        return [AgentInstance.from_model(m) for m in models]

    def get_by_mission(self, mission_id: str) -> list[AgentInstance]:
        """Get all agent instances for a mission."""
        models = self._repository.list_by_mission(mission_id)
        return [AgentInstance.from_model(m) for m in models]

    def get_children(self, parent_agent_id: str) -> list[AgentInstance]:
        """Get child agents of a parent agent."""
        models = self._repository.list_by_parent(parent_agent_id)
        return [AgentInstance.from_model(m) for m in models]

    def get_agent_tree(self, root_agent_id: str) -> AgentInstance | None:
        """Get the full agent tree starting from a root agent."""
        root = self.get(root_agent_id)
        if root is None:
            return None
        
        # Recursively build tree
        def build_tree(agent: AgentInstance) -> AgentInstance:
            children = self.get_children(agent.id)
            agent.child_agent_ids = tuple(c.id for c in children)
            for child in children:
                build_tree(child)
            return agent
        
        return build_tree(root)

    def detect_stale_agents(self, timeout_seconds: float = 60.0) -> list[AgentInstance]:
        """Detect agents with stale heartbeats."""
        agents = self._repository.list_stale_heartbeats(timeout_seconds)
        stale = []
        
        for agent_model in agents:
            if agent_model.last_heartbeat is None:
                continue
            elapsed = (datetime.now(UTC) - agent_model.last_heartbeat).total_seconds()
            if elapsed > timeout_seconds:
                stale.append(AgentInstance.from_model(agent_model))
                
        return stale

    def get_all_active_agents(self) -> list[AgentInstance]:
        """Get all agents in active states."""
        active_statuses = [
            AgentInstanceStatus.SPAWNED,
            AgentInstanceStatus.STARTING,
            AgentInstanceStatus.RUNNING,
            AgentInstanceStatus.WAITING,
            AgentInstanceStatus.PAUSED,
        ]
        agents = []
        for status in active_statuses:
            models = self._repository.list_by_status(status.value)
            agents.extend(AgentInstance.from_model(m) for m in models)
        return agents

    def _generate_id(self) -> str:
        from uuid import uuid4
        return uuid4().hex