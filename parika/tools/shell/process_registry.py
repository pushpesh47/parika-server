"""
PARIKA Shell Tool - Process Registry

Implements `ShellProcessRegistry`, the shared collaborator
`shell.background`, `shell.processes`, and `shell.kill` all delegate
to for spawning, tracking, inspecting, and terminating background
processes.

Every spawned process is tracked under a PARIKA-generated
`process_id` (a `uuid4().hex`, not the raw OS pid, so identity survives
OS pid reuse). Two daemon reader threads per process (one for stdout,
one for stderr) drain output into a bounded buffer
(`output_buffer_max_bytes` - oldest bytes dropped first, the same
bounded-collection shape `filesystem.walk`'s `max_walk_entries` already
uses), and a third daemon thread waits for the process to exit so its
status/exit code are recorded without any caller needing to poll.

Process termination escalates via `psutil` (already a project
dependency, already used by `ResourceManager` for CPU/memory/disk
stats - this is its first use for process control):
`terminate()`, wait up to `kill_grace_period_seconds`, then `kill()`
on timeout.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

import psutil

from parika.core.logger.logger import Logger

from .exceptions import ShellBackgroundLimitExceededError, UnknownProcessError
from .process_record import ShellProcessRecord, ShellProcessStatus


class _TrackedProcess:
    """
    Internal, mutable bookkeeping for one spawned process.
    """

    __slots__ = (
        "process_id",
        "popen",
        "command",
        "cwd",
        "started_at",
        "status",
        "exit_code",
        "stdout_buffer",
        "stderr_buffer",
    )

    def __init__(
        self,
        *,
        process_id: str,
        popen: subprocess.Popen,
        command: tuple[str, ...],
        cwd: Path,
    ) -> None:
        self.process_id = process_id
        self.popen = popen
        self.command = command
        self.cwd = cwd
        self.started_at = datetime.now(UTC)
        self.status = ShellProcessStatus.RUNNING
        self.exit_code: int | None = None
        self.stdout_buffer = ""
        self.stderr_buffer = ""


class ShellProcessRegistry:
    """
    Tracks every background process spawned by the Shell Tool.
    """

    def __init__(
        self,
        *,
        logger: Logger,
        output_buffer_max_bytes: int,
        max_background_processes: int,
        kill_grace_period_seconds: float,
    ) -> None:
        """
        Initialize the registry.

        Args:
            logger:
                PARIKA Logger component.

            output_buffer_max_bytes:
                Upper bound on captured stdout/stderr bytes retained
                per process.

            max_background_processes:
                Upper bound on simultaneously `RUNNING` processes.

            kill_grace_period_seconds:
                How long `kill()` waits after a graceful `terminate()`
                before escalating to `kill()`.
        """

        self._logger = logger.get_logger(__name__)
        self._output_buffer_max_bytes = output_buffer_max_bytes
        self._max_background_processes = max_background_processes
        self._kill_grace_period_seconds = kill_grace_period_seconds

        self._lock = RLock()
        self._processes: dict[str, _TrackedProcess] = {}

    def spawn(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
    ) -> ShellProcessRecord:
        """
        Spawn a detached background process.

        Raises:
            ShellBackgroundLimitExceededError:
                If spawning would exceed `max_background_processes`
                currently `RUNNING`.
        """

        with self._lock:
            running = sum(
                1
                for tracked in self._processes.values()
                if self._snapshot(tracked).status is ShellProcessStatus.RUNNING
            )

            if running >= self._max_background_processes:
                raise ShellBackgroundLimitExceededError(
                    f"Cannot spawn another background process: "
                    f"{running} are already running, at the "
                    f"configured limit of {self._max_background_processes}."
                )

            popen = subprocess.Popen(  # noqa: S603
                list(command),
                cwd=str(cwd),
                env=dict(env) if env is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            tracked = _TrackedProcess(
                process_id=uuid4().hex,
                popen=popen,
                command=tuple(command),
                cwd=cwd,
            )
            self._processes[tracked.process_id] = tracked

        threading.Thread(
            target=self._drain_stream,
            args=(tracked, popen.stdout, "stdout"),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._drain_stream,
            args=(tracked, popen.stderr, "stderr"),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._await_exit,
            args=(tracked,),
            daemon=True,
        ).start()

        self._logger.info(
            "Spawned background process '%s' (pid=%s): %s",
            tracked.process_id,
            popen.pid,
            command,
        )

        return self._snapshot(tracked)

    def list_all(self) -> tuple[ShellProcessRecord, ...]:
        """
        Return a snapshot of every tracked process.
        """

        with self._lock:
            return tuple(
                self._snapshot(tracked) for tracked in self._processes.values()
            )

    def get(self, process_id: str) -> ShellProcessRecord:
        """
        Return a snapshot of one tracked process.

        Raises:
            UnknownProcessError:
                If `process_id` was never spawned by this registry.
        """

        return self._snapshot(self._require(process_id))

    def kill(self, process_id: str) -> ShellProcessRecord:
        """
        Terminate a tracked background process.

        Escalates from a graceful `terminate()` to a forceful `kill()`
        if the process has not exited within
        `kill_grace_period_seconds`.

        Raises:
            UnknownProcessError:
                If `process_id` was never spawned by this registry, or
                is not one still tracked by this process (a process
                this Shell Tool did not spawn is never attempted).
        """

        tracked = self._require(process_id)
        pid = tracked.popen.pid

        with contextlib.suppress(psutil.NoSuchProcess):
            psutil.Process(pid).terminate()

        try:
            tracked.popen.wait(timeout=self._kill_grace_period_seconds)

        except subprocess.TimeoutExpired:
            with contextlib.suppress(psutil.NoSuchProcess):
                psutil.Process(pid).kill()

            with contextlib.suppress(subprocess.TimeoutExpired):
                tracked.popen.wait(timeout=self._kill_grace_period_seconds)

        with self._lock:
            tracked.status = ShellProcessStatus.KILLED

            if tracked.exit_code is None:
                tracked.exit_code = tracked.popen.poll()

        self._logger.info(
            "Killed background process '%s' (pid=%s).", process_id, pid
        )

        return self._snapshot(tracked)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require(self, process_id: str) -> _TrackedProcess:
        with self._lock:
            tracked = self._processes.get(process_id)

        if tracked is None:
            raise UnknownProcessError(f"Unknown process id '{process_id}'.")

        return tracked

    def _snapshot(self, tracked: _TrackedProcess) -> ShellProcessRecord:
        with self._lock:
            if (
                tracked.status is ShellProcessStatus.RUNNING
                and tracked.popen.poll() is not None
            ):
                tracked.status = ShellProcessStatus.EXITED
                tracked.exit_code = tracked.popen.returncode

            return ShellProcessRecord(
                process_id=tracked.process_id,
                pid=tracked.popen.pid,
                command=tracked.command,
                cwd=tracked.cwd,
                status=tracked.status,
                started_at=tracked.started_at,
                exit_code=tracked.exit_code,
                stdout_tail=tracked.stdout_buffer,
                stderr_tail=tracked.stderr_buffer,
            )

    def _drain_stream(self, tracked: _TrackedProcess, stream, which: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                with self._lock:
                    if which == "stdout":
                        tracked.stdout_buffer = self._trim(
                            tracked.stdout_buffer + line
                        )
                    else:
                        tracked.stderr_buffer = self._trim(
                            tracked.stderr_buffer + line
                        )

        except Exception:
            self._logger.exception(
                "Error draining %s for process '%s'.",
                which,
                tracked.process_id,
            )

        finally:
            with contextlib.suppress(Exception):
                stream.close()

    def _trim(self, text: str) -> str:
        encoded = text.encode("utf-8", errors="ignore")

        if len(encoded) <= self._output_buffer_max_bytes:
            return text

        return encoded[-self._output_buffer_max_bytes :].decode(
            "utf-8", errors="ignore"
        )

    def _await_exit(self, tracked: _TrackedProcess) -> None:
        exit_code = tracked.popen.wait()

        with self._lock:
            if tracked.status is ShellProcessStatus.RUNNING:
                tracked.status = ShellProcessStatus.EXITED

            tracked.exit_code = exit_code
