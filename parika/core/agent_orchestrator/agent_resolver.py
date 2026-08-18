"""
PARIKA Agent Resolver

Resolves which agent should handle a given task based on specialization,
capabilities, and policies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from parika.core.agent_orchestrator.agent_profile import AgentProfile
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_specialization import AgentSpecialization
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.logger.logger import Logger

from .exceptions import AgentResolutionError, NoSuitableAgentError


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentResolution:
    """
    Result of agent resolution.
    """
    agent: AgentProfile
    """The resolved agent profile"""
    
    confidence: float
    """Confidence score (0.0-1.0) for this resolution"""
    
    matched_capabilities: tuple[str, ...]
    """Capabilities that matched the agent's preferred/allowed list"""
    
    matched_specialization: bool
    """Whether the agent's specialization directly matched"""
    
    reason: str
    """Human-readable reason for this resolution"""


class AgentResolver:
    """
    Resolves which agent should handle a given task.
    
    The resolver evaluates:
    - Task category and requested capabilities
    - Agent specialization
    - Allowed/prohibited capabilities
    - Model/provider suitability
    - Policies
    
    Designed to be extensible for future dependency-aware concurrency.
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        capability_registry: CapabilityRegistry,
        logger: Logger,
    ) -> None:
        """
        Initialize the agent resolver.

        Args:
            agent_registry:
                Registry of available agents.

            capability_registry:
                Registry used to retrieve capability definitions for category lookup.

            logger:
                Logger service used for diagnostic logging.
        """

        self._agent_registry = agent_registry
        self._capability_registry = capability_registry
        self._logger = logger.get_logger(__name__)

    def resolve(
        self,
        capability_id: str,
        *,
        preferred_specialization: AgentSpecialization | None = None,
        required_categories: frozenset[CapabilityCategory] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResolution:
        """
        Resolve the best agent for a capability.

        Args:
            capability_id:
                The capability to execute.
            
            preferred_specialization:
                Optional preferred specialization hint.
            
            required_categories:
                Optional required capability categories.
            
            context:
                Optional additional context for resolution.

        Returns:
            AgentResolution with the selected agent.

        Raises:
            NoSuitableAgentError:
                If no suitable agent can be found.
        """

        # Get capability definition for category
        capability_def = None
        capability_category = None
        if self._capability_registry.contains(capability_id):
            capability_def = self._capability_registry.get(capability_id)
            capability_category = capability_def.category

        # Find candidate agents
        candidates = self._find_candidates(
            capability_id=capability_id,
            capability_category=capability_category,
            preferred_specialization=preferred_specialization,
            required_categories=required_categories,
        )

        if not candidates:
            raise NoSuitableAgentError(
                f"No suitable agent found for capability '{capability_id}'."
            )

        # Score and select best agent
        scored = self._score_candidates(
            candidates=candidates,
            capability_id=capability_id,
            capability_category=capability_category,
            preferred_specialization=preferred_specialization,
            context=context,
        )

        best_agent, confidence, matched_caps, matched_spec, reason = scored[0]

        self._logger.debug(
            "Resolved agent '%s' for capability '%s' (confidence=%.2f, reason=%s).",
            best_agent.id,
            capability_id,
            confidence,
            reason,
        )

        return AgentResolution(
            agent=best_agent,
            confidence=confidence,
            matched_capabilities=matched_caps,
            matched_specialization=matched_spec,
            reason=reason,
        )

    def _find_candidates(
        self,
        capability_id: str,
        capability_category: CapabilityCategory | None,
        preferred_specialization: AgentSpecialization | None,
        required_categories: frozenset[CapabilityCategory] | None,
    ) -> tuple[AgentProfile, ...]:
        """Find agents that can handle the capability."""
        
        # Start with agents matching preferred specialization
        if preferred_specialization is not None:
            candidates = self._agent_registry.get_by_specialization(preferred_specialization)
        else:
            candidates = self._agent_registry.get_all()

        # Filter by capability access
        filtered = []
        for agent in candidates:
            if agent.can_use_capability(capability_id, capability_category):
                # Check required categories
                if required_categories:
                    if not required_categories.issubset(agent.allowed_categories):
                        continue
                filtered.append(agent)

        # If no agents with preferred specialization, try all agents
        if not filtered and preferred_specialization is not None:
            all_agents = self._agent_registry.get_all()
            for agent in all_agents:
                if agent.can_use_capability(capability_id, capability_category):
                    if required_categories:
                        if not required_categories.issubset(agent.allowed_categories):
                            continue
                    filtered.append(agent)

        return tuple(filtered)

    def _score_candidates(
        self,
        candidates: tuple[AgentProfile, ...],
        capability_id: str,
        capability_category: CapabilityCategory | None,
        preferred_specialization: AgentSpecialization | None,
        context: dict[str, Any] | None,
    ) -> list[tuple[AgentProfile, float, tuple[str, ...], bool, str]]:
        """Score and rank candidate agents."""
        
        scored = []
        
        for agent in candidates:
            score = 0.0
            matched_caps = []
            matched_spec = False
            reasons = []

            # Specialization match (highest weight)
            if preferred_specialization and agent.specialization == preferred_specialization:
                score += 1.0
                matched_spec = True
                reasons.append(f"specialization match ({preferred_specialization.value})")
            elif agent.prefers_capability(capability_id, capability_category):
                score += 0.8
                matched_spec = True
                reasons.append("preferred capability")
            
            # Preferred capability match
            if capability_id in agent.preferred_capabilities:
                score += 0.5
                matched_caps.append(capability_id)
                reasons.append("explicit preferred capability")

            # Category preference
            if capability_category and capability_category in agent.preferred_categories:
                score += 0.3
                reasons.append(f"preferred category ({capability_category.value})")

            # Allowed capability (but not preferred)
            if capability_id in agent.allowed_capabilities and capability_id not in agent.preferred_capabilities:
                score += 0.1
                matched_caps.append(capability_id)
                reasons.append("allowed capability")

            # General agent as fallback
            if agent.specialization == AgentSpecialization.GENERAL:
                score += 0.05
                reasons.append("general fallback")

            # Deterministic tie-breaking by agent ID
            scored.append((agent, score, tuple(matched_caps), matched_spec, "; ".join(reasons)))

        # Sort by score descending, then by agent ID for determinism
        scored.sort(key=lambda x: (-x[1], x[0].id))

        return scored