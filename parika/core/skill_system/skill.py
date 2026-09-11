"""
PARIKA Skill Models

Defines the core skill data structures compatible with the Agent Skills format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class SkillSourceType(StrEnum):
    """Skill source categories."""
    PARIKA_LOCAL = "parika_local"
    USER_INSTALLED = "user_installed"
    COMMUNITY = "community"
    HERMES = "hermes"
    REMOTE = "remote"


class SkillStatus(StrEnum):
    """Skill lifecycle states."""
    DISCOVERED = "discovered"
    SCANNING = "scanning"
    SCANNED = "scanned"
    ACTIVATING = "activating"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    BLOCKED = "blocked"
    ERROR = "error"


class SkillTrustState(StrEnum):
    """Skill trust/security states."""
    DISCOVERED = "discovered"
    SCANNED = "scanned"
    TRUSTED = "trusted"
    RESTRICTED = "restricted"
    BLOCKED = "blocked"


class SkillSecurityStatus(StrEnum):
    """Skill security scan status."""
    PENDING = "pending"
    CLEAN = "clean"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillSource:
    """Skill source definition."""
    id: str
    name: str
    source_type: SkillSourceType
    location: str
    priority: int = 0
    enabled: bool = True
    metadata: MappingProxyType[str, Any] = MappingProxyType({})
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_type": self.source_type.value,
            "location": self.location,
            "priority": self.priority,
            "enabled": self.enabled,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillMetadata:
    """Skill metadata from SKILL.md frontmatter."""
    name: str
    description: str
    version: str
    author: str = ""
    license: str = ""
    platforms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    related_skills: tuple[str, ...] = ()
    compatibility: MappingProxyType[str, Any] = MappingProxyType({})
    allowed_tools: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    required_skills: tuple[str, ...] = ()
    hermes_tags: tuple[str, ...] = ()
    hermes_related_skills: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "license": self.license,
            "platforms": list(self.platforms),
            "tags": list(self.tags),
            "related_skills": list(self.related_skills),
            "compatibility": dict(self.compatibility),
            "allowed_tools": list(self.allowed_tools),
            "required_capabilities": list(self.required_capabilities),
            "required_skills": list(self.required_skills),
            "hermes_tags": list(self.hermes_tags),
            "hermes_related_skills": list(self.hermes_related_skills),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillSecurityRecord:
    """Security scan record for a skill."""
    id: str
    skill_id: str
    scan_result: SkillSecurityStatus
    findings: tuple[dict[str, Any], ...] = ()
    scanned_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    scanner_version: str = "1.0.0"
    scan_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "skill_id": self.skill_id,
            "scan_result": self.scan_result.value,
            "findings": list(self.findings),
            "scanned_at": self.scanned_at.isoformat(),
            "scanner_version": self.scanner_version,
            "scan_duration_ms": self.scan_duration_ms,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class Skill:
    """
    Agent Skill compatible skill representation.

    Follows the Agent Skills model with SKILL.md + optional scripts/references/assets.
    """
    id: str
    source_id: str
    metadata: SkillMetadata
    path: str
    status: SkillStatus = SkillStatus.DISCOVERED
    trust_state: SkillTrustState = SkillTrustState.DISCOVERED
    security_status: SkillSecurityStatus = SkillSecurityStatus.PENDING
    security_record_id: str | None = None
    content_hash: str = ""
    body: str | None = None  # Full SKILL.md content (loaded on activation)
    scripts: MappingProxyType[str, str] = MappingProxyType({})  # script_name -> content
    references: MappingProxyType[str, str] = MappingProxyType({})  # ref_name -> content
    assets: MappingProxyType[str, bytes] = MappingProxyType({})  # asset_name -> content
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    last_used_at: datetime | None = None
    activation_count: int = 0
    error: str | None = None
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "metadata": self.metadata.to_dict(),
            "path": self.path,
            "status": self.status.value,
            "trust_state": self.trust_state.value,
            "security_status": self.security_status.value,
            "security_record_id": self.security_record_id,
            "content_hash": self.content_hash,
            "scripts": dict(self.scripts),
            "references": dict(self.references),
            "assets": {k: "binary" for k in self.assets.keys()},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "activation_count": self.activation_count,
            "error": self.error,
            "tags": list(self.tags),
        }

    @classmethod
    def create_discovered(
        cls,
        source_id: str,
        path: str,
        metadata: SkillMetadata,
        content_hash: str,
    ) -> "Skill":
        """Create a newly discovered skill (metadata only)."""
        now = datetime.now(UTC)
        skill_id = f"skill_{uuid4().hex[:16]}"
        return cls(
            id=skill_id,
            source_id=source_id,
            metadata=metadata,
            path=path,
            status=SkillStatus.DISCOVERED,
            trust_state=SkillTrustState.DISCOVERED,
            security_status=SkillSecurityStatus.PENDING,
            content_hash=content_hash,
            created_at=now,
            updated_at=now,
        )

    def with_body(
        self,
        body: str,
        scripts: MappingProxyType[str, str] | None = None,
        references: MappingProxyType[str, str] | None = None,
        assets: MappingProxyType[str, bytes] | None = None,
    ) -> "Skill":
        """Return a new skill with full body loaded (on activation)."""
        now = datetime.now(UTC)
        return Skill(
            id=self.id,
            source_id=self.source_id,
            metadata=self.metadata,
            path=self.path,
            status=self.status,
            trust_state=self.trust_state,
            security_status=self.security_status,
            security_record_id=self.security_record_id,
            content_hash=self.content_hash,
            body=body,
            scripts=scripts or MappingProxyType({}),
            references=references or MappingProxyType({}),
            assets=assets or MappingProxyType({}),
            created_at=self.created_at,
            updated_at=now,
            activated_at=self.activated_at,
            last_used_at=self.last_used_at,
            activation_count=self.activation_count,
            error=self.error,
            tags=self.tags,
        )

    def activated(self) -> "Skill":
        """Return a new skill marked as activated."""
        now = datetime.now(UTC)
        return Skill(
            id=self.id,
            source_id=self.source_id,
            metadata=self.metadata,
            path=self.path,
            status=SkillStatus.ACTIVE,
            trust_state=self.trust_state,
            security_status=self.security_status,
            security_record_id=self.security_record_id,
            content_hash=self.content_hash,
            body=self.body,
            scripts=self.scripts,
            references=self.references,
            assets=self.assets,
            created_at=self.created_at,
            updated_at=now,
            activated_at=now,
            last_used_at=now,
            activation_count=self.activation_count + 1,
            error=self.error,
            tags=self.tags,
        )

    def with_trust_state(self, trust_state: SkillTrustState, security_status: SkillSecurityStatus | None = None, security_record_id: str | None = None) -> "Skill":
        """Return a new skill with updated trust state."""
        now = datetime.now(UTC)
        return Skill(
            id=self.id,
            source_id=self.source_id,
            metadata=self.metadata,
            path=self.path,
            status=self.status,
            trust_state=trust_state,
            security_status=security_status or self.security_status,
            security_record_id=security_record_id or self.security_record_id,
            content_hash=self.content_hash,
            body=self.body,
            scripts=self.scripts,
            references=self.references,
            assets=self.assets,
            created_at=self.created_at,
            updated_at=now,
            activated_at=self.activated_at,
            last_used_at=self.last_used_at,
            activation_count=self.activation_count,
            error=self.error,
            tags=self.tags,
        )

    def with_status(self, status: SkillStatus, error: str | None = None) -> "Skill":
        """Return a new skill with updated status."""
        now = datetime.now(UTC)
        return Skill(
            id=self.id,
            source_id=self.source_id,
            metadata=self.metadata,
            path=self.path,
            status=status,
            trust_state=self.trust_state,
            security_status=self.security_status,
            security_record_id=self.security_record_id,
            content_hash=self.content_hash,
            body=self.body,
            scripts=self.scripts,
            references=self.references,
            assets=self.assets,
            created_at=self.created_at,
            updated_at=now,
            activated_at=self.activated_at,
            last_used_at=self.last_used_at,
            activation_count=self.activation_count,
            error=error,
            tags=self.tags,
        )

    def is_activatable(self) -> bool:
        """Check if skill can be activated."""
        return (
            self.trust_state in (SkillTrustState.TRUSTED, SkillTrustState.SCANNED)
            and self.security_status in (SkillSecurityStatus.CLEAN, SkillSecurityStatus.WARNING)
            and self.status != SkillStatus.BLOCKED
        )


def generate_skill_id() -> str:
    """Generate a unique skill ID."""
    return f"skill_{uuid4().hex[:16]}"