"""
Unit tests for ShellProcessRegistry.

Uses `sys.executable -c "..."` for every spawned process so these
tests are portable across platforms without depending on any specific
shell binary.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pytest

from parika.tools.shell.exceptions import (
    ShellBackgroundLimitExceededError,
    UnknownProcessError,
)
from parika.tools.shell.process_record import ShellProcessStatus
from parika.tools.shell.process_registry import ShellProcessRegistry


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


def _registry(
    *,
    output_buffer_max_bytes: int = 65536,
    max_background_processes: int = 20,
    kill_grace_period_seconds: float = 2.0,
) -> ShellProcessRegistry:
    return ShellProcessRegistry(
        logger=_FakeLogger(),  # type: ignore[arg-type]
        output_buffer_max_bytes=output_buffer_max_bytes,
        max_background_processes=max_background_processes,
        kill_grace_period_seconds=kill_grace_period_seconds,
    )


def _wait_until_not_running(registry: ShellProcessRegistry, process_id: str, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if registry.get(process_id).status is not ShellProcessStatus.RUNNING:
            return

        time.sleep(0.02)

    raise AssertionError(f"Process '{process_id}' did not finish within {timeout}s.")


class TestSpawn:
    def test_spawn_tracks_and_captures_output(self, tmp_path: Path) -> None:
        registry = _registry()

        record = registry.spawn(
            [sys.executable, "-c", "print('hello from shell tool')"],
            cwd=tmp_path,
        )

        assert record.pid > 0
        _wait_until_not_running(registry, record.process_id)

        final = registry.get(record.process_id)
        assert final.status is ShellProcessStatus.EXITED
        assert final.exit_code == 0
        assert "hello from shell tool" in final.stdout_tail

    def test_spawn_captures_stderr_separately(self, tmp_path: Path) -> None:
        registry = _registry()

        record = registry.spawn(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('oops\\n')",
            ],
            cwd=tmp_path,
        )
        _wait_until_not_running(registry, record.process_id)

        final = registry.get(record.process_id)
        assert "oops" in final.stderr_tail
        assert "oops" not in final.stdout_tail

    def test_spawn_raises_when_background_limit_exceeded(
        self, tmp_path: Path
    ) -> None:
        registry = _registry(max_background_processes=1)

        first = registry.spawn(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            cwd=tmp_path,
        )

        try:
            with pytest.raises(ShellBackgroundLimitExceededError):
                registry.spawn(
                    [sys.executable, "-c", "print('second')"], cwd=tmp_path
                )
        finally:
            registry.kill(first.process_id)

    def test_output_buffer_is_bounded(self, tmp_path: Path) -> None:
        registry = _registry(output_buffer_max_bytes=64)

        record = registry.spawn(
            [
                sys.executable,
                "-c",
                "print('x' * 1000)",
            ],
            cwd=tmp_path,
        )
        _wait_until_not_running(registry, record.process_id)

        final = registry.get(record.process_id)
        assert len(final.stdout_tail.encode("utf-8")) <= 64


class TestListAndGet:
    def test_list_all_includes_every_spawned_process(
        self, tmp_path: Path
    ) -> None:
        registry = _registry()

        first = registry.spawn(
            [sys.executable, "-c", "print('a')"], cwd=tmp_path
        )
        second = registry.spawn(
            [sys.executable, "-c", "print('b')"], cwd=tmp_path
        )

        ids = {record.process_id for record in registry.list_all()}
        assert {first.process_id, second.process_id} <= ids

    def test_get_raises_for_unknown_process_id(self) -> None:
        registry = _registry()

        with pytest.raises(UnknownProcessError):
            registry.get("does-not-exist")


class TestKill:
    def test_kill_stops_a_running_process(self, tmp_path: Path) -> None:
        registry = _registry(kill_grace_period_seconds=2.0)

        record = registry.spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
        )

        killed = registry.kill(record.process_id)

        assert killed.status is ShellProcessStatus.KILLED

    def test_kill_raises_for_unknown_process_id(self) -> None:
        registry = _registry()

        with pytest.raises(UnknownProcessError):
            registry.kill("does-not-exist")
