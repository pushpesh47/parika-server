"""
PARIKA Agent Profile

Defines agent profiles with specialization, capabilities, and policies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from parika.core.capability_registry.capability_category import CapabilityCategory

from .agent_specialization import AgentSpecialization


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentProfile:
    """
    Defines an agent's identity, specialization, and capability access policy.
    
    Agents have specialization and preferred skills, but skills/capabilities
    belong to the shared PARIKA ecosystem. An agent may use allowed non-preferred
    skills when the task requires it.
    """

    id: str
    """Unique agent identifier"""

    name: str
    """Human-readable agent name"""

    specialization: AgentSpecialization
    """Primary domain specialization"""

    preferred_capabilities: frozenset[str] = frozenset()
    """Capabilities this agent prefers and is optimized for"""

    allowed_capabilities: frozenset[str] = frozenset()
    """Capabilities this agent may use (includes preferred)"""

    prohibited_capabilities: frozenset[str] = frozenset()
    """Capabilities this agent must not directly use"""

    preferred_categories: frozenset[CapabilityCategory] = frozenset()
    """Capability categories this agent prefers"""

    allowed_categories: frozenset[CapabilityCategory] = frozenset()
    """Capability categories this agent may use"""

    preferred_providers: frozenset[str] = frozenset()
    """Preferred provider IDs"""

    preferred_models: frozenset[str] = frozenset()
    """Preferred model IDs"""

    model_constraints: MappingProxyType[str, Any] = MappingProxyType({})
    """Model selection constraints (e.g., min_context_window, required_capabilities)"""

    behavioral_policies: MappingProxyType[str, Any] = MappingProxyType({})
    """Behavioral policies (e.g., reasoning_depth, verbosity, tool_calling_style)"""

    resource_constraints: MappingProxyType[str, Any] = MappingProxyType({})
    """Resource constraints (e.g., max_tokens, max_duration, cost_limit)"""

    delegation_policy: str = "allow"
    """Delegation policy: 'allow', 'restricted', 'prohibited'"""

    metadata: MappingProxyType[str, Any] = MappingProxyType({})
    """Additional metadata"""

    def can_use_capability(self, capability_id: str, capability_category: CapabilityCategory) -> bool:
        """Check if this agent can use a specific capability."""
        if capability_id in self.prohibited_capabilities:
            return False
        if self.allowed_capabilities and capability_id not in self.allowed_capabilities:
            # Support prefix matching for wildcard patterns (e.g., "repository_intelligence.*",
            # "vision.provider_*", "image.provider_*")
            for allowed in self.allowed_capabilities:
                if allowed.endswith("*") and capability_id.startswith(allowed[:-1]):
                    return True
            return False
        if self.allowed_categories and capability_category not in self.allowed_categories:
            return False
        return True

    def prefers_capability(self, capability_id: str, capability_category: CapabilityCategory) -> bool:
        """Check if this agent prefers a specific capability."""
        if capability_id in self.preferred_capabilities:
            return True
        if self.preferred_categories and capability_category in self.preferred_categories:
            return True
        return False

    def is_specialized_for(self, capability_id: str, capability_category: CapabilityCategory) -> bool:
        """Check if this agent's specialization matches a capability."""
        return self.prefers_capability(capability_id, capability_category)