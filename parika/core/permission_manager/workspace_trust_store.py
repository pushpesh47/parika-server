"""
PARIKA Permission Manager - Workspace Trust Store

Implements `RuntimeTrustWriter`, the small persistence helper
`WorkspacePermissionManager` uses to make an "Always trust this
workspace" decision survive a restart.

Writes go to `config/runtime.toml` - the existing, already-documented
auto-managed configuration layer (see
`parika/core/configuration/configuration.py`) - using `tomlkit` (an
existing project dependency) so any existing formatting and comments
in that file are preserved rather than clobbered by a plain
`tomllib`/`dict`-based rewrite.

Every write is atomic: content is written to a temporary file in the
same directory and moved into place with `os.replace()` - the same
atomic-write pattern `parika.tools.filesystem.operations.write()`
already uses - so a crash or a concurrent read can never observe a
partially written `runtime.toml`, and a failure to persist never
corrupts the existing file.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from threading import RLock

import tomlkit
from tomlkit import TOMLDocument

from parika.core.logger.logger import Logger


class RuntimeTrustWriter:
    """
    Persists "Always trust" workspace decisions into `runtime.toml`.
    """

    def __init__(self, *, runtime_toml_path: Path, logger: Logger) -> None:
        """
        Initialize the writer.

        Args:
            runtime_toml_path:
                Absolute path to `config/runtime.toml`.

            logger:
                PARIKA Logger component.
        """

        self._runtime_toml_path = runtime_toml_path
        self._logger = logger.get_logger(__name__)
        self._lock = RLock()

    def add_trusted_workspace(self, workspace: Path) -> None:
        """
        Add a workspace to `[filesystem].trusted_workspaces` in
        `runtime.toml`, creating the file if it does not exist yet.

        Idempotent: adding the same workspace twice does not create a
        duplicate entry.

        Args:
            workspace:
                The resolved, absolute workspace directory to persist.
        """

        workspace_text = str(workspace)

        with self._lock:
            document = self._load_or_create_document()

            filesystem_table = document.get("filesystem")

            if filesystem_table is None:
                filesystem_table = tomlkit.table()
                document["filesystem"] = filesystem_table

            trusted_workspaces = filesystem_table.get("trusted_workspaces")

            if trusted_workspaces is None:
                trusted_workspaces = tomlkit.array()
                filesystem_table["trusted_workspaces"] = trusted_workspaces

            if workspace_text in tuple(trusted_workspaces):
                self._logger.debug(
                    "Workspace '%s' is already persisted as trusted; "
                    "skipping write.",
                    workspace_text,
                )
                return

            trusted_workspaces.append(workspace_text)

            self._write_atomically(document)

        self._logger.info(
            "Persisted '%s' as an always-trusted workspace in '%s'.",
            workspace_text,
            self._runtime_toml_path,
        )

    def _load_or_create_document(self) -> TOMLDocument:
        """
        Load `runtime.toml` if it exists, or start a new, empty
        document.

        Notes:
            Assumes the caller already holds `self._lock`.
        """

        if not self._runtime_toml_path.exists():
            return tomlkit.document()

        with self._runtime_toml_path.open("r", encoding="utf-8") as stream:
            return tomlkit.parse(stream.read())

    def _write_atomically(self, document: TOMLDocument) -> None:
        """
        Write `document` to `runtime.toml` atomically.

        Content is written to a temporary file in the same directory,
        flushed, `fsync`-ed, and then moved into place with
        `os.replace()`, so a reader never observes a partially written
        file and a crash mid-write leaves the previous file untouched.

        Notes:
            Assumes the caller already holds `self._lock`.
        """

        self._runtime_toml_path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temp_name = tempfile.mkstemp(
            dir=self._runtime_toml_path.parent,
            prefix=f".{self._runtime_toml_path.name}.",
            suffix=".tmp",
        )

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(tomlkit.dumps(document))
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temp_name, self._runtime_toml_path)

        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)

            raise
