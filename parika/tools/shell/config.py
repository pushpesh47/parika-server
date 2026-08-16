"""
PARIKA Shell Tool - Configuration

Reads the `[shell]` TOML section through the existing `Configuration`
Core component and exposes it as a small, typed, read-only snapshot,
following the same pattern as `parika/tools/filesystem/config.py`.

Security posture: `enabled` defaults to `False` - the Shell Module
registers no Capabilities or Tools at all until explicitly opted into
(see `parika.modules.shell.driver.ShellModuleDriver.start()`), mirroring
how the Filesystem/Web Search Modules already no-op when disabled.

For backward compatibility with the pre-existing
`[security].allow_shell_commands` configuration key (already present
in `config/defaults.toml`, previously unused by any code since no
Shell Tool existed), `[shell].enabled` is authoritative when present;
when `[shell]` is absent from every configuration layer entirely,
`[security].allow_shell_commands` is used instead, so an operator who
already set that key keeps its exact meaning with zero migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from parika.core.configuration.configuration import Configuration

DEFAULT_ENABLED = False
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_BACKGROUND_PROCESSES = 20
DEFAULT_OUTPUT_BUFFER_MAX_BYTES = 65536
DEFAULT_KILL_GRACE_PERIOD_SECONDS = 5.0
DEFAULT_ALLOW_SHELL_STRING = False
DEFAULT_INHERIT_ENVIRONMENT = True
DEFAULT_WORKSPACE_FALLBACK = "data"

LEGACY_ALLOW_SHELL_COMMANDS_CONFIG_KEY = "security.allow_shell_commands"


@dataclass(frozen=True, slots=True, kw_only=True)
class ShellToolConfig:
    """
    Immutable, typed snapshot of `[shell]` configuration.
    """

    enabled: bool = DEFAULT_ENABLED
    """Whether the Shell Module should be active at all."""

    default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    """Default `shell.execute` timeout when the caller omits one."""

    max_timeout_seconds: float = DEFAULT_MAX_TIMEOUT_SECONDS
    """
    Upper bound on `shell.execute`'s `timeout_seconds` argument,
    regardless of what the caller requests.
    """

    max_background_processes: int = DEFAULT_MAX_BACKGROUND_PROCESSES
    """Upper bound on simultaneously tracked background processes."""

    output_buffer_max_bytes: int = DEFAULT_OUTPUT_BUFFER_MAX_BYTES
    """
    Upper bound on captured stdout/stderr bytes retained per background
    process - oldest bytes are dropped first once exceeded.
    """

    kill_grace_period_seconds: float = DEFAULT_KILL_GRACE_PERIOD_SECONDS
    """
    How long `shell.kill` waits after a graceful `terminate()` before
    escalating to `kill()`.
    """

    allow_shell_string: bool = DEFAULT_ALLOW_SHELL_STRING
    """
    Whether a single `str` `command` (executed with `shell=True`
    through the platform default shell) is accepted, in addition to
    the safe, default `list[str]` argv form (`shell=False`). Off by
    default - an explicit, higher-risk opt-in.
    """

    inherit_environment: bool = DEFAULT_INHERIT_ENVIRONMENT
    """Whether spawned processes inherit the current environment."""

    default_workspace: Path | None = None
    """
    Resolved `[workspace].default_workspace`, used as `shell.execute`/
    `shell.background`'s default `cwd` when the caller omits one.
    `None` only when `configuration` is `None`.
    """


def load_shell_config(configuration: Configuration | None) -> ShellToolConfig:
    """
    Build a `ShellToolConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default - which, for
            `enabled`, means `False` (the Shell Module registers
            nothing).

    Returns:
        The resolved, immutable configuration snapshot.
    """

    if configuration is None:
        return ShellToolConfig()

    project_root = configuration.get_project_root()

    raw_enabled = configuration.get("shell.enabled", None)

    if raw_enabled is None:
        raw_enabled = configuration.get(
            LEGACY_ALLOW_SHELL_COMMANDS_CONFIG_KEY, DEFAULT_ENABLED
        )

    raw_default_workspace = configuration.get(
        "workspace.default_workspace", DEFAULT_WORKSPACE_FALLBACK
    )
    default_workspace: Path | None = None

    if raw_default_workspace:
        default_workspace = Path(str(raw_default_workspace))

        if not default_workspace.is_absolute():
            default_workspace = project_root / default_workspace

    return ShellToolConfig(
        enabled=bool(raw_enabled),
        default_timeout_seconds=float(
            configuration.get(
                "shell.default_timeout_seconds", DEFAULT_TIMEOUT_SECONDS
            )
        ),
        max_timeout_seconds=float(
            configuration.get(
                "shell.max_timeout_seconds", DEFAULT_MAX_TIMEOUT_SECONDS
            )
        ),
        max_background_processes=int(
            configuration.get(
                "shell.max_background_processes",
                DEFAULT_MAX_BACKGROUND_PROCESSES,
            )
        ),
        output_buffer_max_bytes=int(
            configuration.get(
                "shell.output_buffer_max_bytes",
                DEFAULT_OUTPUT_BUFFER_MAX_BYTES,
            )
        ),
        kill_grace_period_seconds=float(
            configuration.get(
                "shell.kill_grace_period_seconds",
                DEFAULT_KILL_GRACE_PERIOD_SECONDS,
            )
        ),
        allow_shell_string=bool(
            configuration.get(
                "shell.allow_shell_string", DEFAULT_ALLOW_SHELL_STRING
            )
        ),
        inherit_environment=bool(
            configuration.get(
                "shell.inherit_environment", DEFAULT_INHERIT_ENVIRONMENT
            )
        ),
        default_workspace=default_workspace,
    )
