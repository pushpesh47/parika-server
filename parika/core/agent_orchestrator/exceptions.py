"""
PARIKA Agent Orchestrator Exceptions
"""

from __future__ import annotations


class AgentOrchestrationError(Exception):
    """Base exception for agent orchestration errors."""
    pass


class AgentRegistryError(AgentOrchestrationError):
    """Base exception for agent registry errors."""
    pass


class AgentAlreadyRegisteredError(AgentRegistryError):
    """Raised when attempting to register an agent that already exists."""
    pass


class AgentNotFoundError(AgentRegistryError):
    """Raised when an agent is not found in the registry."""
    pass


class AgentResolutionError(AgentOrchestrationError):
    """Base exception for agent resolution errors."""
    pass


class NoSuitableAgentError(AgentResolutionError):
    """Raised when no suitable agent can be found for a capability."""
    pass


class DelegationNotAllowedError(AgentOrchestrationError):
    """Raised when delegation is not allowed by policy."""
    pass