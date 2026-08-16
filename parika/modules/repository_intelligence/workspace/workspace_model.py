"""
PARIKA Repository Intelligence - Workspace Model

Immutable value objects modeling the Workspace -> Repository ->
Project hierarchy. Each object carries only metadata (no behavior) --
the same discipline `KnowledgeSource`/`Tool`/`Goal` already follow.
"Module"/"File" are intentionally not separate dataclasses beyond this
point: a file is already represented by the Coding Tool's own
`coding_files`/`coding_symbols` rows (see
docs/development/Module_Guide.md section
5.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class GitMetadata:
    """
    Read-only Git metadata for one repository. Populated only via
    `git_reader.py`'s three fixed, read-only queries -- Git is never
    used to modify a repository.
    """

    current_branch: str | None = None
    remote_url: str | None = None
    last_commit_summary: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectSummary:
    """
    One detected project/package beneath a repository -- Project
    Awareness's structural facts (see
    docs/development/Module_Guide.md
    section 7.2).
    """

    root: Path
    ecosystem: str
    manifest_path: Path
    framework: str | None = None
    package_manager: str | None = None
    build_system: str | None = None
    test_framework: str | None = None
    linter: str | None = None
    formatter: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositorySummary:
    """
    One discovered repository beneath a workspace root.
    """

    root: Path
    is_git_repository: bool = False
    git_metadata: GitMetadata | None = None
    readme_path: Path | None = None
    projects: tuple[ProjectSummary, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceSnapshot:
    """
    A workspace's full discovered structure: every repository (and,
    beneath each, every detected project) found under `root`.
    """

    root: Path
    repositories: tuple[RepositorySummary, ...] = ()
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
