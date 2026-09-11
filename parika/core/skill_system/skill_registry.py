"""
PARIKA Skill Registry

Central registry for skill management with discovery, activation, and lifecycle.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.skill_system.skill import (
    Skill,
    SkillSource,
    SkillSourceType,
    SkillStatus,
    SkillTrustState,
    SkillSecurityStatus,
    generate_skill_id,
)
from parika.core.skill_system.skill_parser import SkillParser


@dataclass(slots=True, kw_only=True)
class SkillSourceRecord:
    """Registered skill source."""
    source: SkillSource
    skill_ids: set[str] = field(default_factory=set)
    last_scan: datetime | None = None
    skill_count: int = 0


class SkillRegistry:
    """
    Registry for skills and skill sources.

    Manages skill discovery, activation, security scanning, and lifecycle.
    Follows PARIKA's existing registry patterns.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = threading.RLock()

        # Skill sources by ID
        self._sources: dict[str, SkillSourceRecord] = {}

        # Skills by ID
        self._skills: dict[str, Skill] = {}

        # Skill index by source
        self._source_index: dict[str, set[str]] = {}

        # Skill index by name (for finding)
        self._name_index: dict[str, set[str]] = {}

        # Skill index by tags
        self._tag_index: dict[str, set[str]] = {}

        # Skill index by status
        self._status_index: dict[SkillStatus, set[str]] = {}

        # Skill index by trust state
        self._trust_index: dict[SkillTrustState, set[str]] = {}

        # Skill index by security status
        self._security_index: dict[SkillSecurityStatus, set[str]] = {}

        # Parser
        self._parser = SkillParser()

        # Security scanner (set later)
        self._security_scanner: SkillSecurityScanner | None = None

    def register_source(self, source: SkillSource) -> None:
        """Register a skill source."""
        with self._lock:
            if source.id in self._sources:
                raise ValueError(f"Skill source '{source.id}' already registered")

            record = SkillSourceRecord(source=source)
            self._sources[source.id] = record
            self._source_index[source.id] = set()

            self._logger.info("Registered skill source '%s' (%s)", source.name, source.source_type.value)
            self._event_bus.publish("skill.source.registered", {"source_id": source.id, "name": source.name})

    def unregister_source(self, source_id: str) -> None:
        """Unregister a skill source and all its skills."""
        with self._lock:
            record = self._sources.get(source_id)
            if not record:
                raise ValueError(f"Skill source '{source_id}' not found")

            # Remove all skills from this source
            for skill_id in list(record.skill_ids):
                self._remove_skill(skill_id)

            del self._sources[source_id]
            del self._source_index[source_id]

            self._logger.info("Unregistered skill source '%s'", source_id)
            self._event_bus.publish("skill.source.unregistered", {"source_id": source_id})

    def discover_skills(self, source_id: str, recursive: bool = True) -> list[Skill]:
        """
        Discover skills from a registered source.

        Args:
            source_id: Source to discover from
            recursive: Whether to recurse into subdirectories

        Returns:
            List of newly discovered skills
        """
        with self._lock:
            record = self._sources.get(source_id)
            if not record:
                raise ValueError(f"Skill source '{source_id}' not found")

            source = record.source
            if not source.enabled:
                self._logger.warning("Skill source '%s' is disabled", source_id)
                return []

            location = Path(source.location)
            if not location.exists():
                self._logger.warning("Skill source location does not exist: %s", location)
                return []

        # Discover outside lock to avoid blocking
        discovered = self._discover_skills_from_path(source, location, recursive)

        with self._lock:
            new_skills = []
            for skill in discovered:
                if skill.id not in self._skills:
                    self._add_skill(skill)
                    new_skills.append(skill)

            record.last_scan = datetime.now(UTC)
            record.skill_count = len(record.skill_ids)

            self._logger.info("Discovered %d new skills from source '%s'", len(new_skills), source_id)
            return new_skills

    def _discover_skills_from_path(
        self,
        source: SkillSource,
        path: Path,
        recursive: bool,
    ) -> list[Skill]:
        """Discover skills from a filesystem path."""
        skills = []

        if recursive:
            skill_dirs = path.rglob("SKILL.md")
        else:
            skill_dirs = path.glob("SKILL.md")

        for skill_md in skill_dirs:
            skill_dir = skill_md.parent
            try:
                skill = self._parser.parse_skill_file(skill_md, source)
                skills.append(skill)
            except Exception as e:
                self._logger.error("Failed to parse skill at %s: %s", skill_md, e)

        return skills

    def _add_skill(self, skill: Skill) -> None:
        """Add a skill to the registry (caller must hold lock)."""
        self._skills[skill.id] = skill
        self._source_index[skill.source_id].add(skill.id)
        self._name_index.setdefault(skill.metadata.name, set()).add(skill.id)

        for tag in skill.metadata.tags:
            self._tag_index.setdefault(tag, set()).add(skill.id)
        for tag in skill.metadata.hermes_tags:
            self._tag_index.setdefault(f"hermes:{tag}", set()).add(skill.id)

        self._status_index.setdefault(skill.status, set()).add(skill.id)
        self._trust_index.setdefault(skill.trust_state, set()).add(skill.id)
        self._security_index.setdefault(skill.security_status, set()).add(skill.id)

        self._event_bus.publish("skill.discovered", {"skill_id": skill.id, "name": skill.metadata.name})

    def _remove_skill(self, skill_id: str) -> None:
        """Remove a skill from the registry (caller must hold lock)."""
        skill = self._skills.get(skill_id)
        if not skill:
            return

        # Remove from indices
        self._source_index[skill.source_id].discard(skill_id)
        self._name_index.get(skill.metadata.name, set()).discard(skill_id)
        for tag in skill.metadata.tags:
            self._tag_index.get(tag, set()).discard(skill_id)
        for tag in skill.metadata.hermes_tags:
            self._tag_index.get(f"hermes:{tag}", set()).discard(skill_id)
        self._status_index.get(skill.status, set()).discard(skill_id)
        self._trust_index.get(skill.trust_state, set()).discard(skill_id)
        self._security_index.get(skill.security_status, set()).discard(skill_id)

        del self._skills[skill_id]
        self._event_bus.publish("skill.removed", {"skill_id": skill_id})

    def get_skill(self, skill_id: str) -> Skill | None:
        """Get a skill by ID."""
        with self._lock:
            return self._skills.get(skill_id)

    def get_skill_by_name(self, name: str) -> list[Skill]:
        """Get skills by name (may return multiple from different sources)."""
        with self._lock:
            skill_ids = self._name_index.get(name, set())
            return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def list_skills(
        self,
        *,
        source_id: str | None = None,
        status: SkillStatus | None = None,
        trust_state: SkillTrustState | None = None,
        security_status: SkillSecurityStatus | None = None,
        tags: tuple[str, ...] = (),
    ) -> list[Skill]:
        """List skills matching filters."""
        with self._lock:
            if source_id:
                skill_ids = self._source_index.get(source_id, set())
            elif tags:
                # Intersection of all tag indices
                tag_sets = [self._tag_index.get(tag, set()) for tag in tags]
                if not tag_sets:
                    skill_ids = set()
                else:
                    skill_ids = set.intersection(*tag_sets)
            else:
                skill_ids = set(self._skills.keys())

            if status:
                skill_ids &= self._status_index.get(status, set())
            if trust_state:
                skill_ids &= self._trust_index.get(trust_state, set())
            if security_status:
                skill_ids &= self._security_index.get(security_status, set())

            return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def activate_skill(self, skill_id: str) -> Skill:
        """
        Activate a skill (load full content).

        This is the progressive disclosure step - load SKILL.md body,
        scripts, references, and assets only when needed.
        """
        with self._lock:
            skill = self._skills.get(skill_id)
            if not skill:
                raise ValueError(f"Skill '{skill_id}' not found")

            if not skill.is_activatable():
                raise ValueError(
                    f"Skill '{skill_id}' cannot be activated: "
                    f"trust={skill.trust_state.value}, "
                    f"security={skill.security_status.value}, "
                    f"status={skill.status.value}"
                )

        # Load full skill content outside lock
        full_skill = self._parser.load_full_skill(skill)

        with self._lock:
            # Update skill with activated state
            activated_skill = full_skill.activated()
            self._skills[skill_id] = activated_skill

            # Update indices
            old_status = skill.status
            if old_status != SkillStatus.ACTIVE:
                self._status_index.get(old_status, set()).discard(skill_id)
                self._status_index.setdefault(SkillStatus.ACTIVE, set()).add(skill_id)

            self._event_bus.publish("skill.activated", {"skill_id": skill_id, "name": activated_skill.metadata.name})
            self._logger.info("Activated skill '%s'", activated_skill.metadata.name)

            return activated_skill

    def update_skill_trust(
        self,
        skill_id: str,
        trust_state: SkillTrustState,
        security_status: SkillSecurityStatus | None = None,
        security_record_id: str | None = None,
    ) -> Skill:
        """Update skill trust state after security scan."""
        with self._lock:
            skill = self._skills.get(skill_id)
            if not skill:
                raise ValueError(f"Skill '{skill_id}' not found")

            updated = skill.with_trust_state(
                trust_state=trust_state,
                security_status=security_status,
                security_record_id=security_record_id,
            )
            self._skills[skill_id] = updated

            # Update indices
            self._trust_index.get(skill.trust_state, set()).discard(skill_id)
            self._trust_index.setdefault(trust_state, set()).add(skill_id)

            if security_status and security_status != skill.security_status:
                self._security_index.get(skill.security_status, set()).discard(skill_id)
                self._security_index.setdefault(security_status, set()).add(skill_id)

            self._event_bus.publish("skill.trust_updated", {
                "skill_id": skill_id,
                "trust_state": trust_state.value,
                "security_status": security_status.value if security_status else skill.security_status.value,
            })

            return updated

    def block_skill(self, skill_id: str, reason: str) -> Skill:
        """Block a skill (security/policy violation)."""
        with self._lock:
            skill = self._skills.get(skill_id)
            if not skill:
                raise ValueError(f"Skill '{skill_id}' not found")

            blocked = skill.with_status(SkillStatus.BLOCKED, error=reason)
            self._skills[skill_id] = blocked

            # Update indices
            self._status_index.get(skill.status, set()).discard(skill_id)
            self._status_index.setdefault(SkillStatus.BLOCKED, set()).add(skill_id)
            self._trust_index.get(skill.trust_state, set()).discard(skill_id)
            self._trust_index.setdefault(SkillTrustState.BLOCKED, set()).add(skill_id)

            self._event_bus.publish("skill.blocked", {"skill_id": skill_id, "reason": reason})
            self._logger.warning("Blocked skill '%s': %s", skill_id, reason)

            return blocked

    def set_security_scanner(self, scanner: "SkillSecurityScanner") -> None:
        """Set the security scanner for this registry."""
        self._security_scanner = scanner

    def scan_skill(self, skill_id: str) -> SkillSecurityRecord:
        """Scan a skill for security issues."""
        if not self._security_scanner:
            raise RuntimeError("No security scanner configured")

        with self._lock:
            skill = self._skills.get(skill_id)
            if not skill:
                raise ValueError(f"Skill '{skill_id}' not found")

        # Load full content for scanning
        full_skill = self._parser.load_full_skill(skill)

        # Perform scan
        record = self._security_scanner.scan_skill(full_skill)

        # Update skill with scan results
        trust_state = self._determine_trust_state(record.scan_result)
        self.update_skill_trust(
            skill_id,
            trust_state=trust_state,
            security_status=record.scan_result,
            security_record_id=record.id,
        )

        return record

    def _determine_trust_state(self, scan_result: SkillSecurityStatus) -> SkillTrustState:
        """Determine trust state from scan result."""
        if scan_result == SkillSecurityStatus.BLOCKED:
            return SkillTrustState.BLOCKED
        elif scan_result == SkillSecurityStatus.WARNING:
            return SkillTrustState.RESTRICTED
        elif scan_result == SkillSecurityStatus.CLEAN:
            return SkillTrustState.TRUSTED
        else:
            return SkillTrustState.SCANNED

    def get_source(self, source_id: str) -> SkillSource | None:
        """Get a skill source by ID."""
        with self._lock:
            record = self._sources.get(source_id)
            return record.source if record else None

    def list_sources(self) -> list[SkillSource]:
        """List all registered skill sources."""
        with self._lock:
            return [record.source for record in self._sources.values()]

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            return {
                "total_sources": len(self._sources),
                "total_skills": len(self._skills),
                "by_status": {s.value: len(ids) for s, ids in self._status_index.items()},
                "by_trust": {t.value: len(ids) for t, ids in self._trust_index.items()},
                "by_security": {s.value: len(ids) for s, ids in self._security_index.items()},
            }