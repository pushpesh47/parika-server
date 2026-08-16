"""
PARIKA Repository Intelligence - Workspace Discovery

Walks a workspace root to find every Git repository (a directory
containing `.git`) and, within each, every detected project. Reuses
`iter_files`-shaped direct `pathlib` traversal -- the same "engine
reads its own source content directly" precedent already established
by `CodeKnowledgeEngine`/`DocumentKnowledgeEngine`, not a new one. See
docs/development/Module_Guide.md section
5.4.
"""

from __future__ import annotations

from pathlib import Path

from parika.modules.repository_intelligence.indexing.project_detector import (
    ProjectDetectorRegistry,
)
from parika.modules.repository_intelligence.repository.readme import find_readme
from parika.modules.repository_intelligence.workspace.workspace_model import (
    RepositorySummary,
    WorkspaceSnapshot,
)

DEFAULT_IGNORED_DIRECTORIES: tuple[str, ...] = (
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "target",
)


def discover_workspace(
    root: Path,
    *,
    project_detector_registry: ProjectDetectorRegistry | None = None,
    ignored_directories: tuple[str, ...] = DEFAULT_IGNORED_DIRECTORIES,
    max_repository_depth: int = 3,
) -> WorkspaceSnapshot:
    """
    Discover every repository (and, beneath each, every project)
    under `root`.

    A directory containing a `.git` entry is treated as a repository
    root. If `root` itself is not a Git repository and none is found
    beneath it, `root` is still treated as a single, non-Git
    "repository" so a bare directory a user points PARIKA at is never
    silently skipped.
    """

    registry = project_detector_registry or ProjectDetectorRegistry()
    repository_roots = _find_repository_roots(
        root, ignored_directories=ignored_directories, max_depth=max_repository_depth
    )

    if not repository_roots:
        repository_roots = [root]

    repositories = tuple(
        _summarize_repository(repository_root, registry)
        for repository_root in repository_roots
    )

    return WorkspaceSnapshot(root=root, repositories=repositories)


def _summarize_repository(
    repository_root: Path, registry: ProjectDetectorRegistry
) -> RepositorySummary:
    is_git_repository = (repository_root / ".git").exists()
    readme_path = find_readme(repository_root)
    projects = registry.detect(repository_root)

    return RepositorySummary(
        root=repository_root,
        is_git_repository=is_git_repository,
        readme_path=readme_path,
        projects=projects,
    )


def _find_repository_roots(
    root: Path, *, ignored_directories: tuple[str, ...], max_depth: int
) -> list[Path]:
    if not root.is_dir():
        return []

    found: list[Path] = []

    if (root / ".git").exists():
        found.append(root)

    if max_depth <= 0:
        return found

    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found

    for entry in entries:
        if not entry.is_dir() or entry.name in ignored_directories:
            continue

        found.extend(
            _find_repository_roots(
                entry,
                ignored_directories=ignored_directories,
                max_depth=max_depth - 1,
            )
        )

    return found
