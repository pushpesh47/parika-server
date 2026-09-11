"""
PARIKA Hermes Skill Interoperability

Provides adapter to use Hermes skills through PARIKA's skill system.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.skill_system.skill import (
    Skill,
    SkillMetadata,
    SkillSource,
    SkillSourceType,
    SkillStatus,
    SkillTrustState,
    SkillSecurityStatus,
)
from parika.core.skill_system.skill_parser import SkillParser
from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.skill_system.skill_security import SkillSecurityScanner


@dataclass(slots=True, kw_only=True)
class HermesSkillInfo:
    """Information about a Hermes skill."""
    name: str
    path: str
    description: str
    version: str
    tags: list[str]
    related_skills: list[str]
    hermes_metadata: dict[str, Any]


class HermesSkillAdapter:
    """
    Adapts Hermes skills to PARIKA's skill system.

    Allows Hermes skills to be discovered, validated, and used
    through PARIKA's normal skill pipeline.
    """

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry,
        security_scanner: SkillSecurityScanner,
        event_bus: EventBus,
        logger: Logger,
        hermes_binary: str = "hermes",
        hermes_skills_dir: str | None = None,
    ) -> None:
        self._skill_registry = skill_registry
        self._security_scanner = security_scanner
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)
        self._hermes_binary = hermes_binary
        self._hermes_skills_dir = hermes_skills_dir or Path.home() / ".hermes" / "skills"
        self._parser = SkillParser()

    def import_hermes_skill(self, skill_name: str, source_id: str = "hermes") -> Skill | None:
        """
        Import a Hermes skill into PARIKA's skill registry.

        Args:
            skill_name: Name of the Hermes skill to import
            source_id: Skill source ID (default: "hermes")

        Returns:
            Imported Skill or None if failed
        """
        # Find the skill in Hermes
        hermes_skill = self._find_hermes_skill(skill_name)
        if not hermes_skill:
            self._logger.warning("Hermes skill '%s' not found", skill_name)
            return None

        # Get or create Hermes source
        source = self._skill_registry.get_source(source_id)
        if not source:
            source = SkillSource(
                id=source_id,
                name="Hermes Skills",
                source_type=SkillSourceType.HERMES,
                location=str(self._hermes_skills_dir),
                priority=50,
            )
            self._skill_registry.register_source(source)

        # Parse the skill
        skill_path = Path(hermes_skill.path)
        try:
            skill = self._parser.parse_skill_directory(skill_path, source)

            # Add Hermes-specific metadata
            skill = Skill(
                id=skill.id,
                source_id=skill.source_id,
                metadata=SkillMetadata(
                    name=skill.metadata.name,
                    description=skill.metadata.description,
                    version=skill.metadata.version,
                    author=skill.metadata.author,
                    license=skill.metadata.license,
                    platforms=skill.metadata.platforms,
                    tags=skill.metadata.tags + tuple(hermes_skill.tags),
                    related_skills=skill.metadata.related_skills + tuple(hermes_skill.related_skills),
                    compatibility=skill.metadata.compatibility,
                    allowed_tools=skill.metadata.allowed_tools,
                    required_capabilities=skill.metadata.required_capabilities,
                    required_skills=skill.metadata.required_skills,
                    hermes_tags=tuple(hermes_skill.tags),
                    hermes_related_skills=tuple(hermes_skill.related_skills),
                ),
                path=skill.path,
                status=skill.status,
                trust_state=skill.trust_state,
                security_status=skill.security_status,
                content_hash=skill.content_hash,
            )

            # Register with PARIKA
            self._skill_registry._add_skill(skill)  # Accessing protected for internal use

            self._event_bus.publish("hermes.skill.imported", {
                "skill_id": skill.id,
                "hermes_skill": skill_name,
            })

            self._logger.info("Imported Hermes skill '%s' as '%s'", skill_name, skill.id)
            return skill

        except Exception as e:
            self._logger.error("Failed to import Hermes skill '%s': %s", skill_name, e)
            return None

    def _find_hermes_skill(self, skill_name: str) -> HermesSkillInfo | None:
        """Find a skill in Hermes skills directory."""
        skills_dir = Path(self._hermes_skills_dir)

        # Search recursively
        for skill_md in skills_dir.rglob("SKILL.md"):
            skill_dir = skill_md.parent
            dir_name = skill_dir.name

            # Match by directory name or skill name in SKILL.md
            if dir_name == skill_name:
                return self._parse_hermes_skill_info(skill_dir)

            # Also check the skill name in frontmatter
            try:
                content = skill_md.read_text(encoding='utf-8')
                if f"name: {skill_name}" in content or f"name: '{skill_name}'" in content or f'name: "{skill_name}"' in content:
                    return self._parse_hermes_skill_info(skill_dir)
            except Exception:
                pass

        return None

    def _parse_hermes_skill_info(self, skill_dir: Path) -> HermesSkillInfo:
        """Parse Hermes skill info from SKILL.md."""
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text(encoding='utf-8')

        # Parse frontmatter
        import re
        import yaml

        frontmatter_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if frontmatter_match:
            frontmatter_text = frontmatter_match.group(1)
            frontmatter = yaml.safe_load(frontmatter_text) or {}
        else:
            frontmatter = {}

        hermes_meta = frontmatter.get('metadata', {}).get('hermes', {}) if 'metadata' in frontmatter else {}

        return HermesSkillInfo(
            name=frontmatter.get('name', skill_dir.name),
            path=str(skill_dir),
            description=frontmatter.get('description', ''),
            version=frontmatter.get('version', '1.0.0'),
            tags=hermes_meta.get('tags', []),
            related_skills=hermes_meta.get('related_skills', []),
            hermes_metadata=hermes_meta,
        )

    def scan_all_hermes_skills(self, source_id: str = "hermes") -> list[Skill]:
        """
        Scan and import all Hermes skills.

        Returns:
            List of imported skills
        """
        skills_dir = Path(self._hermes_skills_dir)
        imported = []

        for skill_md in skills_dir.rglob("SKILL.md"):
            skill_dir = skill_md.parent
            skill_name = skill_dir.name

            skill = self.import_hermes_skill(skill_name, source_id)
            if skill:
                imported.append(skill)

        self._logger.info("Scanned and imported %d Hermes skills", len(imported))
        return imported

    def sync_hermes_skills(self, source_id: str = "hermes") -> dict[str, int]:
        """
        Sync PARIKA skills with Hermes skills.

        Returns:
            Dict with counts: added, updated, removed
        """
        # Get current Hermes skills
        hermes_skills = set()
        for skill_md in Path(self._hermes_skills_dir).rglob("SKILL.md"):
            hermes_skills.add(skill_md.parent.name)

        # Get current PARIKA Hermes skills
        source = self._skill_registry.get_source(source_id)
        if not source:
            return {"added": 0, "updated": 0, "removed": 0}

        parika_skill_ids = self._skill_registry._source_index.get(source_id, set())
        parika_skills = set()
        for skill_id in parika_skill_ids:
            skill = self._skill_registry._skills.get(skill_id)
            if skill:
                parika_skills.add(Path(skill.path).name)

        # Calculate differences
        to_add = hermes_skills - parika_skills
        to_remove = parika_skills - hermes_skills

        added = 0
        for skill_name in to_add:
            skill = self.import_hermes_skill(skill_name, source_id)
            if skill:
                added += 1

        removed = 0
        for skill_name in to_remove:
            # Find and remove
            for skill_id in parika_skill_ids:
                skill = self._skill_registry._skills.get(skill_id)
                if skill and Path(skill.path).name == skill_name:
                    self._skill_registry._remove_skill(skill_id)
                    removed += 1
                    break

        return {
            "added": added,
            "updated": 0,  # Would need version comparison
            "removed": removed,
        }

    def get_hermes_skill_scripts(self, skill_id: str) -> dict[str, str]:
        """Get scripts from a Hermes skill adapted for PARIKA."""
        skill = self._skill_registry.get_skill(skill_id)
        if not skill:
            return {}

        # Return scripts as-is - they can be executed through Hermes runtime
        return dict(skill.scripts)

    def convert_hermes_tool_call(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """
        Convert a Hermes tool call to PARIKA format.

        Hermes tools may have different calling conventions.
        """
        # This would map Hermes tool names to PARIKA tool IDs
        # and convert argument formats
        return {
            "tool": tool_name,
            "arguments": args,
        }