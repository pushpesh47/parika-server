"""
PARIKA Skill Catalog

Provides efficient skill discovery, filtering, and metadata retrieval
without loading full skill content. Implements progressive disclosure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.skill_system.skill import (
    Skill,
    SkillSource,
    SkillSourceType,
    SkillStatus,
    SkillTrustState,
    SkillSecurityStatus,
)
from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.skill_system.skill_parser import SkillParser


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillMetadataOnly:
    """
    Lightweight skill metadata for catalog/discovery.

    Used for listing/filtering without loading full skill body.
    """
    id: str
    source_id: str
    source_name: str
    source_type: SkillSourceType
    name: str
    description: str
    version: str
    tags: tuple[str, ...]
    trust_state: SkillTrustState
    security_status: SkillSecurityStatus
    status: SkillStatus
    allowed_tools: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    required_skills: tuple[str, ...]
    path: str
    content_hash: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None

    @classmethod
    def from_skill(cls, skill: Skill, source: SkillSource) -> "SkillMetadataOnly":
        return cls(
            id=skill.id,
            source_id=skill.source_id,
            source_name=source.name,
            source_type=source.source_type,
            name=skill.metadata.name,
            description=skill.metadata.description,
            version=skill.metadata.version,
            tags=skill.metadata.tags,
            trust_state=skill.trust_state,
            security_status=skill.security_status,
            status=skill.status,
            allowed_tools=skill.metadata.allowed_tools,
            required_capabilities=skill.metadata.required_capabilities,
            required_skills=skill.metadata.required_skills,
            path=skill.path,
            content_hash=skill.content_hash,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            error=skill.error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type.value,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": list(self.tags),
            "trust_state": self.trust_state.value,
            "security_status": self.security_status.value,
            "status": self.status.value,
            "allowed_tools": list(self.allowed_tools),
            "required_capabilities": list(self.required_capabilities),
            "required_skills": list(self.required_skills),
            "path": self.path,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "error": self.error,
        }


class SkillCatalog:
    """
    Skill catalog for discovery and filtering.

    Provides metadata-only access to skills for efficient browsing
    and selection without loading full skill content.
    """

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        configuration: Configuration,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._registry = registry
        self._configuration = configuration
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._parser = SkillParser()

        # Configured skill directories
        self._skill_dirs: list[Path] = []

    def initialize(self) -> None:
        """Initialize catalog from configuration."""
        self._load_configured_sources()
        self._discover_all_sources()

    def _load_configured_sources(self) -> None:
        """Load skill sources from configuration."""
        # PARIKA local skills
        parika_skills_dir = self._configuration.get_project_root() / "skills"
        if parika_skills_dir.exists():
            source = SkillSource(
                id="parika_local",
                name="PARIKA Local Skills",
                source_type=SkillSourceType.PARIKA_LOCAL,
                location=str(parika_skills_dir),
                priority=100,
            )
            self._registry.register_source(source)

        # User installed skills
        user_skills_dir = self._configuration.get_project_root() / "user_skills"
        if user_skills_dir.exists():
            source = SkillSource(
                id="user_installed",
                name="User Installed Skills",
                source_type=SkillSourceType.USER_INSTALLED,
                location=str(user_skills_dir),
                priority=80,
            )
            self._registry.register_source(source)

        # Community skills directory
        community_skills_dir = self._configuration.get_project_root() / "community_skills"
        if community_skills_dir.exists():
            source = SkillSource(
                id="community",
                name="Community Skills",
                source_type=SkillSourceType.COMMUNITY,
                location=str(community_skills_dir),
                priority=60,
            )
            self._registry.register_source(source)

        # Hermes skills
        hermes_skills_dir = Path.home() / ".hermes" / "skills"
        if hermes_skills_dir.exists():
            source = SkillSource(
                id="hermes",
                name="Hermes Skills",
                source_type=SkillSourceType.HERMES,
                location=str(hermes_skills_dir),
                priority=50,
            )
            self._registry.register_source(source)

        # Additional configured sources
        extra_sources = self._configuration.get("skills.sources", [])
        for src_config in extra_sources:
            source = SkillSource(
                id=src_config.get("id", f"custom_{len(self._registry._sources)}"),
                name=src_config.get("name", "Custom Skills"),
                source_type=SkillSourceType(src_config.get("type", "remote")),
                location=src_config.get("location", ""),
                priority=src_config.get("priority", 10),
                enabled=src_config.get("enabled", True),
                metadata=src_config.get("metadata", {}),
            )
            self._registry.register_source(source)

    def _discover_all_sources(self) -> None:
        """Discover skills from all registered sources."""
        for source in self._registry.list_sources():
            if source.enabled:
                try:
                    self._registry.discover_skills(source.id)
                except Exception as e:
                    self._logger.error("Failed to discover skills from source '%s': %s", source.id, e)

    def search(
        self,
        *,
        query: str | None = None,
        source_type: SkillSourceType | None = None,
        trust_state: SkillTrustState | None = None,
        security_status: SkillSecurityStatus | None = None,
        status: SkillStatus | None = None,
        tags: tuple[str, ...] = (),
        required_capability: str | None = None,
        allowed_tool: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SkillMetadataOnly]:
        """
        Search skills with filters.

        Returns lightweight metadata only - not full skill content.
        """
        # Build filter function
        def matches(skill: Skill) -> bool:
            if source_type:
                source = self._registry.get_source(skill.source_id)
                if not source or source.source_type != source_type:
                    return False
            if trust_state and skill.trust_state != trust_state:
                return False
            if security_status and skill.security_status != security_status:
                return False
            if status and skill.status != status:
                return False
            if tags:
                skill_tags = set(skill.metadata.tags) | set(skill.metadata.hermes_tags)
                if not all(tag in skill_tags for tag in tags):
                    return False
            if required_capability and required_capability not in skill.metadata.required_capabilities:
                return False
            if allowed_tool and allowed_tool not in skill.metadata.allowed_tools:
                return False
            if query:
                query_lower = query.lower()
                if (query_lower not in skill.metadata.name.lower() and
                    query_lower not in skill.metadata.description.lower() and
                    not any(query_lower in tag.lower() for tag in skill.metadata.tags)):
                    return False
            return True

        # Get candidate skills
        all_skills = self._registry.list_skills()
        filtered = [s for s in all_skills if matches(s)]

        # Sort by relevance (priority: trust, then name)
        filtered.sort(key=lambda s: (
            s.trust_state != SkillTrustState.TRUSTED,
            s.trust_state != SkillTrustState.SCANNED,
            s.metadata.name.lower(),
        ))

        # Apply pagination
        paginated = filtered[offset:offset + limit]

        # Convert to metadata only
        results = []
        for skill in paginated:
            source = self._registry.get_source(skill.source_id)
            if source:
                results.append(SkillMetadataOnly.from_skill(skill, source))

        return results

    def get_skill_metadata(self, skill_id: str) -> SkillMetadataOnly | None:
        """Get lightweight metadata for a specific skill."""
        skill = self._registry.get_skill(skill_id)
        if not skill:
            return None

        source = self._registry.get_source(skill.source_id)
        if not source:
            return None

        return SkillMetadataOnly.from_skill(skill, source)

    def get_activatable_skills(
        self,
        *,
        required_capability: str | None = None,
        allowed_tool: str | None = None,
    ) -> list[SkillMetadataOnly]:
        """
        Get skills that can be activated (trusted + clean/warning security).

        Used by planner/agent for dynamic skill selection.
        """
        return self.search(
            trust_state=SkillTrustState.TRUSTED,
            security_status=SkillSecurityStatus.CLEAN,
            status=SkillStatus.ACTIVE,
            required_capability=required_capability,
            allowed_tool=allowed_tool,
        )

    def get_skills_for_capability(self, capability_id: str) -> list[SkillMetadataOnly]:
        """Get skills that declare a required capability."""
        return self.search(required_capability=capability_id)

    def get_skills_for_tool(self, tool_id: str) -> list[SkillMetadataOnly]:
        """Get skills that declare an allowed tool."""
        return self.search(allowed_tool=tool_id)

    def get_skill_compatibility(
        self,
        skill_id: str,
        available_capabilities: set[str],
        available_tools: set[str],
        available_skills: set[str],
    ) -> dict[str, Any]:
        """
        Check skill compatibility with current environment.

        Returns compatibility report with missing requirements.
        """
        skill = self._registry.get_skill(skill_id)
        if not skill:
            return {"compatible": False, "reason": "Skill not found"}

        missing_capabilities = set(skill.metadata.required_capabilities) - available_capabilities
        missing_tools = set(skill.metadata.allowed_tools) - available_tools
        missing_skills = set(skill.metadata.required_skills) - available_skills

        return {
            "compatible": not (missing_capabilities or missing_tools or missing_skills),
            "missing_capabilities": list(missing_capabilities),
            "missing_tools": list(missing_tools),
            "missing_skills": list(missing_skills),
            "required_capabilities": list(skill.metadata.required_capabilities),
            "required_tools": list(skill.metadata.allowed_tools),
            "required_skills": list(skill.metadata.required_skills),
        }

    def refresh_source(self, source_id: str) -> int:
        """Refresh skills from a specific source."""
        new_skills = self._registry.discover_skills(source_id)
        return len(new_skills)

    def refresh_all(self) -> int:
        """Refresh all skill sources."""
        total = 0
        for source in self._registry.list_sources():
            if source.enabled:
                total += self.refresh_source(source.id)
        return total

    def get_stats(self) -> dict[str, Any]:
        """Get catalog statistics."""
        registry_stats = self._registry.get_stats()
        return {
            "registry": registry_stats,
            "sources": [
                {
                    "id": s.id,
                    "name": s.name,
                    "type": s.source_type.value,
                    "enabled": s.enabled,
                    "skill_count": self._registry._source_index.get(s.id, 0),
                }
                for s in self._registry.list_sources()
            ],
        }