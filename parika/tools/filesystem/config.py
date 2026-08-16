"""
PARIKA Filesystem Tool - Configuration

Reads the `[filesystem]` (and `[workspace]`) TOML sections through the
existing `Configuration` Core component and exposes them as a small,
typed, read-only snapshot, following the same pattern as
`parika/tools/web_search/config.py`.

Security posture: with no `Configuration` supplied at all,
`trusted_workspaces` defaults to empty and every mutating/destructive
operation is rejected by `security.PathSecurity` - a Filesystem Module
constructed without configuration is inert-but-safe, never silently
permissive for writes/deletes. Reads are never gated by this
configuration at all (see `security.py`).

`trusted_workspaces` prefers the new `[filesystem].trusted_workspaces` key;
when that key is absent from every configuration layer, it falls back
to the deprecated `[filesystem].allowed_roots` alias, so existing
installations keep working unchanged. `[workspace].default_workspace`
is always included in the effective set, whether or not it is also
listed explicitly - the single named source of truth every present and
future Tool that touches a workspace reuses (see
`parika.core.permission_manager.workspace_permission_manager` for the
same computation, shared centrally with the Shell Tool).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from parika.core.configuration.configuration import Configuration

DEFAULT_ALLOW_WRITE = True
DEFAULT_ALLOW_DELETE = False
DEFAULT_SEARCH_RECURSIVE = True
DEFAULT_MAX_WALK_ENTRIES = 5000
DEFAULT_WATCH_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_WATCH_MAX_DURATION_SECONDS = 10.0
DEFAULT_WORKSPACE_FALLBACK = "data"


@dataclass(frozen=True, slots=True, kw_only=True)
class FilesystemToolConfig:
    """
    Immutable, typed snapshot of `[filesystem]` configuration.
    """

    enabled: bool = True
    """Whether the Filesystem Module should be active at all."""

    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)
    """
    Every trusted workspace root mutating/destructive operations may
    touch without escalation, resolved from `[filesystem].
    trusted_workspaces` (falling back to the deprecated `allowed_roots`
    alias) plus `[workspace].default_workspace`. Empty only when
    `configuration` is `None` - reads are unaffected either way (see
    `security.PathSecurity`).
    """

    allow_write: bool = DEFAULT_ALLOW_WRITE
    allow_delete: bool = DEFAULT_ALLOW_DELETE

    default_search_recursive: bool = DEFAULT_SEARCH_RECURSIVE
    max_walk_entries: int = DEFAULT_MAX_WALK_ENTRIES
    watch_poll_interval_seconds: float = DEFAULT_WATCH_POLL_INTERVAL_SECONDS
    watch_max_duration_seconds: float = DEFAULT_WATCH_MAX_DURATION_SECONDS


def load_filesystem_config(
    configuration: Configuration | None,
) -> FilesystemToolConfig:
    """
    Build a `FilesystemToolConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default - which, for
            `allowed_roots`, means empty (no filesystem access at
            all) until a `Configuration` explicitly grants some.

    Returns:
        The resolved, immutable configuration snapshot.
    """

    if configuration is None:
        return FilesystemToolConfig()

    project_root = configuration.get_project_root()

    raw_roots = configuration.get("filesystem.trusted_workspaces", None)

    if raw_roots is None:
        raw_roots = configuration.get("filesystem.allowed_roots", [])

    resolved_roots: list[Path] = []

    if isinstance(raw_roots, (list, tuple)):
        for raw_root in raw_roots:
            candidate = Path(str(raw_root))

            if not candidate.is_absolute():
                candidate = project_root / candidate

            if candidate not in resolved_roots:
                resolved_roots.append(candidate)

    raw_default_workspace = configuration.get(
        "workspace.default_workspace", DEFAULT_WORKSPACE_FALLBACK
    )

    if raw_default_workspace:
        default_workspace = Path(str(raw_default_workspace))

        if not default_workspace.is_absolute():
            default_workspace = project_root / default_workspace

        if default_workspace not in resolved_roots:
            resolved_roots.append(default_workspace)

    return FilesystemToolConfig(
        enabled=bool(configuration.get("filesystem.enabled", True)),
        allowed_roots=tuple(resolved_roots),
        allow_write=bool(
            configuration.get("filesystem.allow_write", DEFAULT_ALLOW_WRITE)
        ),
        allow_delete=bool(
            configuration.get("filesystem.allow_delete", DEFAULT_ALLOW_DELETE)
        ),
        default_search_recursive=bool(
            configuration.get(
                "filesystem.default_search_recursive",
                DEFAULT_SEARCH_RECURSIVE,
            )
        ),
        max_walk_entries=int(
            configuration.get(
                "filesystem.max_walk_entries", DEFAULT_MAX_WALK_ENTRIES
            )
        ),
        watch_poll_interval_seconds=float(
            configuration.get(
                "filesystem.watch_poll_interval_seconds",
                DEFAULT_WATCH_POLL_INTERVAL_SECONDS,
            )
        ),
        watch_max_duration_seconds=float(
            configuration.get(
                "filesystem.watch_max_duration_seconds",
                DEFAULT_WATCH_MAX_DURATION_SECONDS,
            )
        ),
    )
