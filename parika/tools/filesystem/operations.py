"""
PARIKA Filesystem Tool - Operations

Pure, stdlib-only implementations of every Filesystem Tool operation.

Every function here receives an already-resolved, already
security-checked `Path` (see `security.PathSecurity.resolve()`) and
returns a plain, JSON-serializable dict. None of these functions
perform path validation, confinement checks, or permission-flag
enforcement themselves - that is `driver.py`'s responsibility, applied
identically before any operation ever reaches this module.

Implemented entirely with `pathlib`, `os`, `shutil`, `stat`, `fnmatch`,
and `tempfile` - no third-party dependency, matching the project's
standard-library-first convention already established by
`web_search`'s HTML parsing and `runtime_info`'s clock access.
"""

from __future__ import annotations

import base64
import contextlib
import fnmatch
import os
import shutil
import stat as stat_module
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .exceptions import (
    FilesystemAlreadyExistsError,
    FilesystemPathNotFoundError,
    InvalidFilesystemArgumentError,
)

DEFAULT_ENCODING = "utf-8"


def _entry_info(entry: Path) -> dict[str, Any]:
    try:
        st = entry.stat()
    except OSError:
        return {"path": str(entry), "name": entry.name, "error": "stat failed"}

    return {
        "path": str(entry),
        "name": entry.name,
        "is_dir": entry.is_dir(),
        "is_file": entry.is_file(),
        "is_symlink": entry.is_symlink(),
        "size": st.st_size,
    }


def _require_exists(path: Path) -> None:
    if not path.exists():
        raise FilesystemPathNotFoundError(f"Path '{path}' does not exist.")


def read(
    path: Path,
    *,
    encoding: str = DEFAULT_ENCODING,
    binary: bool = False,
) -> dict[str, Any]:
    """
    Read the content of a file.

    Args:
        binary:
            When True, reads raw bytes and returns them base64-encoded
            under `content_base64` instead of decoding as text - for
            file types (e.g. PDF, DOCX, XLSX, PPTX, ODT, ODS, or any
            other binary format) where text decoding is inappropriate.
            This is raw byte-level access only, not content
            extraction/parsing. Default `False` preserves the
            original text-only behavior exactly.
    """

    _require_exists(path)

    if path.is_dir():
        raise InvalidFilesystemArgumentError(
            f"Path '{path}' is a directory; use filesystem.list or "
            "filesystem.walk instead."
        )

    if binary:
        data = path.read_bytes()

        return {
            "path": str(path),
            "content_base64": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
            "size": len(data),
        }

    content = path.read_text(encoding=encoding)

    return {
        "path": str(path),
        "content": content,
        "encoding": encoding,
        "size": len(content.encode(encoding)),
    }


def write(
    path: Path,
    *,
    content: str = "",
    content_base64: str | None = None,
    encoding: str = DEFAULT_ENCODING,
    binary: bool = False,
    create_parents: bool = True,
    append: bool = False,
) -> dict[str, Any]:
    """
    Write content to a file.

    A non-append write is performed atomically: content is written to
    a temporary file in the same directory, flushed, `fsync`-ed, and
    then moved into place with `os.replace()`, so a reader never
    observes a partially written file and a crash mid-write leaves
    the original file untouched.

    Args:
        binary:
            When True, `content_base64` is base64-decoded and written
            as raw bytes instead of encoding `content` as text.
            Default `False` preserves the original text-only behavior
            exactly.
    """

    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)

    if not path.parent.exists():
        raise FilesystemPathNotFoundError(
            f"Parent directory '{path.parent}' does not exist "
            "(pass create_parents=true to create it)."
        )

    if binary:
        payload = base64.b64decode(content_base64 or "")
    else:
        payload = content.encode(encoding)

    encoded_length = len(payload)

    if append:
        with path.open("ab") as handle:
            handle.write(payload)

        return {
            "path": str(path),
            "bytes_written": encoded_length,
            "mode": "append",
        }

    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )

    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_name, path)

    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)

        raise

    return {
        "path": str(path),
        "bytes_written": encoded_length,
        "mode": "overwrite",
    }


def list_directory(
    path: Path,
    *,
    pattern: str | None = None,
) -> dict[str, Any]:
    """
    List the immediate entries of a directory, optionally filtered
    by a glob-style filename pattern.
    """

    _require_exists(path)

    if not path.is_dir():
        raise InvalidFilesystemArgumentError(f"Path '{path}' is not a directory.")

    if pattern:
        entries = sorted(path.glob(pattern), key=lambda entry: entry.name)
    else:
        entries = sorted(path.iterdir(), key=lambda entry: entry.name)

    return {
        "path": str(path),
        "pattern": pattern,
        "entries": [_entry_info(entry) for entry in entries],
    }


def search(
    path: Path,
    *,
    pattern: str,
    recursive: bool = True,
) -> dict[str, Any]:
    """
    Search a directory tree for entries whose filename matches a
    glob-style pattern (e.g. `*.py`).
    """

    _require_exists(path)

    if not path.is_dir():
        raise InvalidFilesystemArgumentError(f"Path '{path}' is not a directory.")

    matches: list[str] = []

    if recursive:
        for root, dirs, files in os.walk(path):
            root_path = Path(root)

            for name in fnmatch.filter(dirs + files, pattern):
                matches.append(str(root_path / name))
    else:
        for entry in path.iterdir():
            if fnmatch.fnmatch(entry.name, pattern):
                matches.append(str(entry))

    return {
        "path": str(path),
        "pattern": pattern,
        "recursive": recursive,
        "matches": sorted(matches),
    }


def copy(
    source: Path,
    destination: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Copy a file or directory to a new location.
    """

    _require_exists(source)

    if destination.exists() and not overwrite:
        raise FilesystemAlreadyExistsError(
            f"Destination '{destination}' already exists "
            "(pass overwrite=true to replace it)."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)

    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=overwrite)
    else:
        shutil.copy2(source, destination)

    return {
        "source": str(source),
        "destination": str(destination),
    }


def move(
    source: Path,
    destination: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Move or rename a file or directory.
    """

    _require_exists(source)

    if destination.exists():
        if not overwrite:
            raise FilesystemAlreadyExistsError(
                f"Destination '{destination}' already exists "
                "(pass overwrite=true to replace it)."
            )

        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))

    return {
        "source": str(source),
        "destination": str(destination),
    }


def delete(path: Path, *, recursive: bool = False) -> dict[str, Any]:
    """
    Delete a file or directory.
    """

    _require_exists(path)

    if path.is_dir():
        if not recursive:
            raise InvalidFilesystemArgumentError(
                f"'{path}' is a directory; pass recursive=true to "
                "delete it and its contents."
            )

        shutil.rmtree(path)
    else:
        path.unlink()

    return {"path": str(path), "deleted": True}


def mkdir(
    path: Path,
    *,
    parents: bool = True,
    exist_ok: bool = True,
) -> dict[str, Any]:
    """
    Create a directory, optionally creating any missing parents.
    """

    path.mkdir(parents=parents, exist_ok=exist_ok)

    return {"path": str(path), "created": True}


def exists(path: Path) -> dict[str, Any]:
    """
    Check whether a path exists.
    """

    return {
        "path": str(path),
        "exists": path.exists(),
        "is_file": path.is_file() if path.exists() else False,
        "is_dir": path.is_dir() if path.exists() else False,
    }


def info(path: Path) -> dict[str, Any]:
    """
    Return metadata about a path: size, type, timestamps, and
    permissions.
    """

    _require_exists(path)

    st = path.stat()

    return {
        "path": str(path),
        "size": st.st_size,
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "is_symlink": path.is_symlink(),
        "modified_at": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
        "created_at": datetime.fromtimestamp(st.st_ctime, tz=UTC).isoformat(),
        "mode": stat_module.filemode(st.st_mode),
    }


def walk(path: Path, *, max_entries: int = 5000) -> dict[str, Any]:
    """
    Recursively list every file and directory beneath a path, up to
    `max_entries`.
    """

    _require_exists(path)

    if not path.is_dir():
        raise InvalidFilesystemArgumentError(f"Path '{path}' is not a directory.")

    entries: list[dict[str, Any]] = []
    truncated = False

    for root, dirs, files in os.walk(path):
        root_path = Path(root)

        for name in sorted(dirs):
            entries.append({"path": str(root_path / name), "is_dir": True})

            if len(entries) >= max_entries:
                truncated = True
                break

        if truncated:
            break

        for name in sorted(files):
            entries.append({"path": str(root_path / name), "is_dir": False})

            if len(entries) >= max_entries:
                truncated = True
                break

        if truncated:
            break

    return {
        "path": str(path),
        "entries": entries,
        "truncated": truncated,
    }


def permissions(path: Path) -> dict[str, Any]:
    """
    Return the permission mode and read/write/execute access of a
    path for the current process.
    """

    _require_exists(path)

    st = path.stat()

    return {
        "path": str(path),
        "mode": stat_module.filemode(st.st_mode),
        "readable": os.access(path, os.R_OK),
        "writable": os.access(path, os.W_OK),
        "executable": os.access(path, os.X_OK),
    }


def _snapshot(path: Path) -> dict[str, tuple[float, int]]:
    snapshot: dict[str, tuple[float, int]] = {}

    if path.is_dir():
        for root, _dirs, files in os.walk(path):
            root_path = Path(root)

            for name in files:
                entry = root_path / name

                try:
                    st = entry.stat()
                except OSError:
                    continue

                snapshot[str(entry)] = (st.st_mtime, st.st_size)
    else:
        st = path.stat()
        snapshot[str(path)] = (st.st_mtime, st.st_size)

    return snapshot


def watch(
    path: Path,
    *,
    interval_seconds: float = 1.0,
    duration_seconds: float = 5.0,
    sleep: Any = time.sleep,
    now: Any = time.monotonic,
) -> dict[str, Any]:
    """
    Observe a path for a bounded duration using stdlib polling and
    report every created, modified, and deleted entry seen.

    This is a synchronous, bounded operation - it blocks for up to
    `duration_seconds` and then returns every change observed during
    that window - because `ToolDriver.execute()` returns a single
    `ToolResponse`, not a stream. `interval_seconds` and
    `duration_seconds` are both configurable (see
    `config.FilesystemToolConfig`) so operators can tune the
    latency/CPU trade-off without a code change.
    """

    _require_exists(path)

    previous = _snapshot(path)
    changes: list[dict[str, str]] = []
    deadline = now() + duration_seconds

    while now() < deadline:
        sleep(interval_seconds)
        current = _snapshot(path)

        for entry_path, meta in current.items():
            if entry_path not in previous:
                changes.append({"path": entry_path, "event": "created"})
            elif previous[entry_path] != meta:
                changes.append({"path": entry_path, "event": "modified"})

        for entry_path in previous:
            if entry_path not in current:
                changes.append({"path": entry_path, "event": "deleted"})

        previous = current

    return {
        "path": str(path),
        "duration_seconds": duration_seconds,
        "interval_seconds": interval_seconds,
        "changes": changes,
    }
