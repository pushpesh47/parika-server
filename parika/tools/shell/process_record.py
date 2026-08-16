"""
PARIKA Shell Tool - Process Record

Defines the immutable snapshot `ShellProcessRegistry` returns for one
tracked background process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class ShellProcessStatus(StrEnum):
    """
    The lifecycle status of one tracked background process.
    """

    RUNNING = "running"
    EXITED = "exited"
    KILLED = "killed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ShellProcessRecord:
    """
    Immutable snapshot of one background process tracked by
    `ShellProcessRegistry`.
    """

    process_id: str
    """
    PARIKA-generated identifier (a `uuid4().hex`, not the raw OS pid,
    so identity survives OS pid reuse).
    """

    pid: int
    """The underlying OS process id."""

    command: tuple[str, ...]
    """The argv this process was spawned with."""

    cwd: Path
    """The working directory this process was spawned in."""

    status: ShellProcessStatus
    """The process's current lifecycle status."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When the process was spawned."""

    exit_code: int | None = None
    """The process's exit code, once known (`None` while `RUNNING`)."""

    stdout_tail: str = ""
    """Captured stdout, bounded by `[shell].output_buffer_max_bytes`."""

    stderr_tail: str = ""
    """Captured stderr, bounded by `[shell].output_buffer_max_bytes`."""
