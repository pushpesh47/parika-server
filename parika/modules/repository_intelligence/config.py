"""
PARIKA Repository Intelligence - Configuration

Reads the `[repository_intelligence]` TOML section, following the
same pattern as `parika/tools/filesystem/config.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from parika.core.configuration.configuration import Configuration
from parika.modules.repository_intelligence.workspace.discovery import (
    DEFAULT_IGNORED_DIRECTORIES,
)

DEFAULT_ENABLED = True
DEFAULT_GIT_RECENT_COMMITS_LIMIT = 20


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryIntelligenceConfig:
    enabled: bool = DEFAULT_ENABLED
    ignored_directories: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_IGNORED_DIRECTORIES
    )
    git_recent_commits_limit: int = DEFAULT_GIT_RECENT_COMMITS_LIMIT


def load_repository_intelligence_config(
    configuration: Configuration | None,
) -> RepositoryIntelligenceConfig:
    if configuration is None:
        return RepositoryIntelligenceConfig()

    raw_ignored = configuration.get(
        "repository_intelligence.ignored_directories",
        list(DEFAULT_IGNORED_DIRECTORIES),
    )

    return RepositoryIntelligenceConfig(
        enabled=bool(
            configuration.get("repository_intelligence.enabled", DEFAULT_ENABLED)
        ),
        ignored_directories=tuple(str(entry) for entry in raw_ignored),
        git_recent_commits_limit=int(
            configuration.get(
                "repository_intelligence.git_recent_commits_limit",
                DEFAULT_GIT_RECENT_COMMITS_LIMIT,
            )
        ),
    )
