"""
PARIKA Agent Selector

Provides dynamic agent selection based on task requirements, capabilities,
skills, and historical performance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_resolver import AgentResolver
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.implementation_registry.implementation_registry import ImplementationRegistry
from parika.core.implementation_registry.implementation_resolver import ImplementationResolver
from parika.core.skill_system.skill_catalog import SkillCatalog
from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentSelectionCriteria:
    """Criteria for agent selection."""
    capability_id: str
    required_skills: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    preferred_runtime: str | None = None
    allowed_runtimes: tuple[str, ...] = ()
    agent_profile_id: str | None = None
    agent_specialization: str | None = None
    max_agents: int = 1
    require_isolation: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentCandidate:
    """A candidate agent for selection."""
    agent_id: str
    agent_profile_id: str
    specialization: str
    matched_skills: tuple[str, ...]
    matched_tools: tuple[str, ...]
    matched_capabilities: tuple[str, ...]
    score: float
    implementation_id: str | None = None


class AgentSelector:
    """
    Selects optimal agents for tasks based on multiple criteria.

    Uses:
    - Agent profiles and specializations
    - Skill compatibility
    - Tool availability
    - Historical performance (experience)
    - Current load
    """

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        agent_resolver: AgentResolver,
        agent_orchestrator: AgentOrchestrator,
        capability_registry: CapabilityRegistry,
        capability_resolver: CapabilityResolver,
        implementation_registry: ImplementationRegistry,
        implementation_resolver: ImplementationResolver,
        skill_registry: SkillRegistry,
        skill_catalog: SkillCatalog,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._agent_registry = agent_registry
        self._agent_resolver = agent_resolver
        self._agent_orchestrator = agent_orchestrator
        self._capability_registry = capability_registry
        self._capability_resolver = capability_resolver
        self._implementation_registry = implementation_registry
        self._implementation_resolver = implementation_resolver
        self._skill_registry = skill_registry
        self._skill_catalog = skill_catalog
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def select_agents(
        self,
        criteria: AgentSelectionCriteria,
        *,
        mission_id: str | None = None,
        task_id: str | None = None,
    ) -> list[AgentCandidate]:
        """
        Select agents matching criteria.

        Returns list of candidates sorted by score (best first).
        """
        # Get all registered agents
        all_agents = self._agent_registry.get_all()

        candidates = []

        for agent_profile in all_agents:
            # Check profile ID match
            if criteria.agent_profile_id and agent_profile.id != criteria.agent_profile_id:
                continue

            # Check specialization match
            if criteria.agent_specialization:
                if agent_profile.specialization.value != criteria.agent_specialization:
                    continue

            # Check capability compatibility
            capability = self._capability_registry.get(criteria.capability_id)
            if not capability:
                continue

            if not agent_profile.can_use_capability(
                criteria.capability_id,
                capability.category
            ):
                continue

            # Check required skills
            missing_skills = set(criteria.required_skills) - set(agent_profile.allowed_capabilities)
            if missing_skills:
                continue

            # Check preferred skills
            matched_preferred_skills = set(criteria.preferred_skills) & set(agent_profile.allowed_capabilities)
            
            # Check required tools
            missing_tools = set(criteria.required_tools) - set(agent_profile.allowed_capabilities)
            if missing_tools:
                continue

            # Score this candidate
            score = self._score_candidate(
                agent_profile,
                criteria,
                matched_preferred_skills,
            )

            # Find matching implementation
            impl = self._find_implementation(agent_profile, criteria)

            candidates.append(AgentCandidate(
                agent_id=agent_profile.id,
                agent_profile_id=agent_profile.id,
                specialization=agent_profile.specialization.value,
                matched_skills=tuple(matched_preferred_skills),
                matched_tools=tuple(set(criteria.required_tools) & set(agent_profile.allowed_capabilities)),
                matched_capabilities=(criteria.capability_id,),
                score=score,
                implementation_id=impl.id if impl else None,
            ))

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Limit to max_agents
        return candidates[:criteria.max_agents]

    def _score_candidate(
        self,
        agent_profile,
        criteria: AgentSelectionCriteria,
        matched_preferred_skills: set[str],
    ) -> float:
        """Score an agent candidate."""
        score = 0.0

        # Base score for capability match
        score += 0.3

        # Skill match bonus
        if criteria.required_skills:
            skill_match_ratio = len(matched_preferred_skills) / max(len(criteria.preferred_skills), 1)
            score += 0.2 * skill_match_ratio

        # Tool match bonus
        matched_tools = set(criteria.required_tools) & set(agent_profile.allowed_capabilities)
        if criteria.required_tools:
            tool_match_ratio = len(matched_tools) / len(criteria.required_tools)
            score += 0.15 * tool_match_ratio

        # Specialization match bonus
        if criteria.agent_specialization and agent_profile.specialization.value == criteria.agent_specialization:
            score += 0.15

        # Profile preference (preferred capabilities)
        if criteria.capability_id in agent_profile.preferred_capabilities:
            score += 0.1

        return min(score, 1.0)

    def _find_implementation(
        self,
        agent_profile,
        criteria: AgentSelectionCriteria,
    ):
        """Find suitable implementation for agent + capability."""
        try:
            # Use implementation resolver to find best implementation
            impls = self._implementation_registry.get_implementations_for_capability(
                criteria.capability_id,
                status="active",
            )

            # Filter by agent's allowed tools/skills
            filtered = []
            for impl in impls:
                tool_ok = all(t in agent_profile.allowed_capabilities for t in impl.metadata.tool_ids)
                skill_ok = all(s in agent_profile.allowed_capabilities for s in impl.metadata.skill_ids)
                if tool_ok and skill_ok:
                    filtered.append(impl)

            if filtered:
                # Return highest experience score
                return max(filtered, key=lambda i: i.experience_score)

        except Exception:
            pass

        return None

    def select_best_agent(
        self,
        criteria: AgentSelectionCriteria,
        **kwargs,
    ) -> AgentCandidate | None:
        """Select the single best agent."""
        candidates = self.select_agents(criteria, **kwargs)
        return candidates[0] if candidates else None

    def get_agent_load(self, agent_profile_id: str) -> dict[str, Any]:
        """Get current load for an agent profile (placeholder)."""
        # Would integrate with actual runtime to get active agent count
        return {
            "profile_id": agent_profile_id,
            "active_agents": 0,
            "max_concurrent": 10,
            "load_factor": 0.0,
        }