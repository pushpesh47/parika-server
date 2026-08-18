"""
PARIKA Agent Orchestrator

Provides the multi-agent execution foundation for PARIKA.
"""

from __future__ import annotations

from .agent_profile import AgentProfile, AgentSpecialization
from .agent_registry import AgentRegistry
from .agent_resolver import AgentResolver
from .agent_orchestrator import AgentOrchestrator
from .exceptions import (
    AgentOrchestrationError,
    AgentRegistryError,
    AgentAlreadyRegisteredError,
    AgentNotFoundError,
    AgentResolutionError,
    NoSuitableAgentError,
    DelegationNotAllowedError,
)

__all__ = [
    "AgentProfile",
    "AgentSpecialization",
    "AgentRegistry",
    "AgentResolver",
    "AgentOrchestrator",
    "AgentOrchestrationError",
    "AgentRegistryError",
    "AgentAlreadyRegisteredError",
    "AgentNotFoundError",
    "AgentResolutionError",
    "NoSuitableAgentError",
    "DelegationNotAllowedError",
]