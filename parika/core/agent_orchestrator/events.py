"""
PARIKA Agent Orchestrator Events
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from parika.core.agent_orchestrator.agent_specialization import AgentSpecialization


@dataclass(frozen=True, slots=True)
class AgentRegistered:
    """Event published when an agent is registered."""
    agent_id: str
    specialization: str


@dataclass(frozen=True, slots=True)
class AgentUnregistered:
    """Event published when an agent is unregistered."""
    agent_id: str


@dataclass(frozen=True, slots=True)
class AgentAssigned:
    """Event published when an agent is assigned to a goal."""
    agent_id: str
    goal_id: str
    capability_id: str
    specialization: str
    confidence: float


@dataclass(frozen=True, slots=True)
class AgentDelegated:
    """Event published when an agent delegates work to another agent."""
    from_agent_id: str
    to_agent_id: str
    capability_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class AgentExecutionStarted:
    """Event published when an agent starts executing a goal."""
    agent_id: str
    goal_id: str
    capability_id: str


@dataclass(frozen=True, slots=True)
class AgentExecutionCompleted:
    """Event published when an agent completes executing a goal."""
    agent_id: str
    goal_id: str
    capability_id: str
    succeeded: bool
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class AgentExecutionFailed:
    """Event published when an agent fails to execute a goal."""
    agent_id: str
    goal_id: str
    capability_id: str
    error: str