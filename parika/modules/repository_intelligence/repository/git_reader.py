"""
PARIKA Repository Intelligence - Git Reader

Read-only Git metadata via three fixed, hardcoded, argv-form `git`
subcommands, run through the existing, unmodified Shell Tool's
`shell.execute` capability -- never a new `gitpython`/`pygit2`
dependency, and never a mutating Git command. Git is READ ONLY: this
is the entire, closed API surface through which this platform ever
touches Git -- see
docs/development/Module_Guide.md section
6.2.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager

SHELL_EXECUTE_TOOL_ID = "tool.shell_execute"


class GitReadError(Exception):
    """Raised when a read-only Git query fails."""


class GitReader:
    """
    Exposes exactly three deterministic, read-only Git queries. This
    class's API surface is a fixed, closed set by design -- any future
    addition must be reviewed against the "Git is read-only" mandate.
    """

    def __init__(self, tool_manager: ToolManager) -> None:
        self._tool_manager = tool_manager

    def current_branch(self, repository_root: Path) -> str | None:
        result = self._run(
            repository_root, ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        )
        return result.strip() or None if result is not None else None

    def remote_url(self, repository_root: Path) -> str | None:
        result = self._run(
            repository_root, ["git", "remote", "get-url", "origin"]
        )
        return result.strip() or None if result is not None else None

    def recent_commits(
        self, repository_root: Path, *, limit: int = 20
    ) -> tuple[str, ...]:
        result = self._run(
            repository_root,
            ["git", "log", f"-n{limit}", "--format=%h %s"],
        )

        if not result:
            return ()

        return tuple(line for line in result.splitlines() if line.strip())

    def _run(self, repository_root: Path, command: list[str]) -> str | None:
        try:
            response = self._tool_manager.execute(
                SHELL_EXECUTE_TOOL_ID,
                ToolRequest(
                    arguments={"command": command, "cwd": str(repository_root)}
                ),
            )
        except Exception:
            return None

        result = response.result

        if not isinstance(result, dict) or result.get("exit_code") != 0:
            return None

        return str(result.get("stdout", ""))
