"""
PARIKA Filesystem Tool - Driver

Implements the `ToolDriver` contract
(`parika.core.tool_manager.driver.ToolDriver`) for every Filesystem
Tool operation.

A single `FilesystemToolDriver` instance is bound to exactly one
`FilesystemOperation` at construction time (see `manifest.py`'s module
docstring for why one Tool per capability is required here). The
Filesystem Module constructs twelve instances - one per operation -
and registers each as its own Tool.

Every operation shares the same two steps before doing any real
filesystem work: resolving and security-checking every path argument
through `security.PathSecurity`, then enforcing `allow_write`/
`allow_delete` for mutating operations. The actual filesystem
mechanics live in `operations.py` as small, independently testable
pure functions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parika.core.permission_manager.workspace_operation import WorkspaceOperation
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from . import operations
from .config import (
    DEFAULT_MAX_WALK_ENTRIES,
    DEFAULT_SEARCH_RECURSIVE,
    DEFAULT_WATCH_MAX_DURATION_SECONDS,
    DEFAULT_WATCH_POLL_INTERVAL_SECONDS,
)
from .exceptions import InvalidFilesystemArgumentError
from .manifest import FilesystemOperation
from .security import PathSecurity


class FilesystemToolDriver:
    """
    ToolDriver implementing one Filesystem Tool operation.
    """

    def __init__(
        self,
        operation: FilesystemOperation,
        *,
        security: PathSecurity,
        default_search_recursive: bool = DEFAULT_SEARCH_RECURSIVE,
        max_walk_entries: int = DEFAULT_MAX_WALK_ENTRIES,
        watch_poll_interval_seconds: float = DEFAULT_WATCH_POLL_INTERVAL_SECONDS,
        watch_max_duration_seconds: float = DEFAULT_WATCH_MAX_DURATION_SECONDS,
    ) -> None:
        """
        Initialize the driver for one operation.

        Args:
            operation:
                The single `FilesystemOperation` this driver instance
                implements.

            security:
                Shared `PathSecurity` boundary every path argument is
                resolved and validated through.

            default_search_recursive:
                Default for `filesystem.search`'s `recursive`
                argument when the caller omits it.

            max_walk_entries:
                Upper bound on entries returned by `filesystem.walk`.

            watch_poll_interval_seconds:
                Default polling interval for `filesystem.watch`.

            watch_max_duration_seconds:
                Upper bound on `filesystem.watch`'s `duration_seconds`
                argument, regardless of what the caller requests -
                so a single call can never block indefinitely.
        """

        self._operation = operation
        self._security = security
        self._default_search_recursive = default_search_recursive
        self._max_walk_entries = max_walk_entries
        self._watch_poll_interval_seconds = watch_poll_interval_seconds
        self._watch_max_duration_seconds = watch_max_duration_seconds

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Execute this driver's bound operation.

        Raises:
            InvalidFilesystemArgumentError:
                If a required argument is missing or invalid.

            PathNotAllowedError:
                If a path argument resolves outside every configured
                `[filesystem].allowed_roots` entry.

            FilesystemOperationNotPermittedError:
                If a mutating/destructive operation is disabled by
                configuration.

            FilesystemPathNotFoundError:
                If an operation requires a path that does not exist.

            FilesystemAlreadyExistsError:
                If `copy`/`move` would overwrite an existing
                destination without `overwrite=true`.
        """

        match self._operation:
            case FilesystemOperation.READ:
                return self._execute_read(request)
            case FilesystemOperation.WRITE:
                return self._execute_write(request)
            case FilesystemOperation.LIST:
                return self._execute_list(request)
            case FilesystemOperation.SEARCH:
                return self._execute_search(request)
            case FilesystemOperation.COPY:
                return self._execute_copy(request)
            case FilesystemOperation.MOVE:
                return self._execute_move(request)
            case FilesystemOperation.DELETE:
                return self._execute_delete(request)
            case FilesystemOperation.MKDIR:
                return self._execute_mkdir(request)
            case FilesystemOperation.EXISTS:
                return self._execute_exists(request)
            case FilesystemOperation.INFO:
                return self._execute_info(request)
            case FilesystemOperation.WALK:
                return self._execute_walk(request)
            case FilesystemOperation.PERMISSIONS:
                return self._execute_permissions(request)
            case FilesystemOperation.WATCH:
                return self._execute_watch(request)

        raise InvalidFilesystemArgumentError(
            f"Unknown filesystem operation: {self._operation!r}."
        )

    def _resolve_path(
        self,
        request: ToolRequest,
        argument_name: str = "path",
        *,
        enforce_roots: bool = True,
        operation: WorkspaceOperation | None = None,
    ) -> Path:
        return self._security.resolve(
            request.arguments.get(argument_name),
            argument_name=argument_name,
            enforce_roots=enforce_roots,
            operation=operation,
        )

    def _execute_read(self, request: ToolRequest) -> ToolResponse:
        # Read-only: always allowed, any resolvable path, unconditionally
        # - see PathSecurity.resolve()'s docstring.
        path = self._resolve_path(request, enforce_roots=False)
        encoding = str(request.arguments.get("encoding", "utf-8"))
        binary = bool(request.arguments.get("binary", False))

        result = operations.read(path, encoding=encoding, binary=binary)

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_write(self, request: ToolRequest) -> ToolResponse:
        self._security.require_write()

        path = self._resolve_path(request, operation=WorkspaceOperation.WRITE)
        binary = bool(request.arguments.get("binary", False))
        content_base64 = request.arguments.get("content_base64")

        if binary:
            if not isinstance(content_base64, str):
                raise InvalidFilesystemArgumentError(
                    "request.arguments['content_base64'] must be a "
                    "string when binary=true."
                )
            content = ""
        else:
            content = request.arguments.get("content", "")

            if not isinstance(content, str):
                raise InvalidFilesystemArgumentError(
                    "request.arguments['content'] must be a string."
                )

        encoding = str(request.arguments.get("encoding", "utf-8"))
        create_parents = bool(request.arguments.get("create_parents", True))
        append = bool(request.arguments.get("append", False))

        result = operations.write(
            path,
            content=content,
            content_base64=content_base64 if binary else None,
            encoding=encoding,
            binary=binary,
            create_parents=create_parents,
            append=append,
        )

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_list(self, request: ToolRequest) -> ToolResponse:
        # Read-only - see _execute_read()'s comment.
        path = self._resolve_path(request, enforce_roots=False)
        pattern = request.arguments.get("pattern")

        result = operations.list_directory(
            path,
            pattern=str(pattern) if pattern else None,
        )

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_search(self, request: ToolRequest) -> ToolResponse:
        # Read-only - see _execute_read()'s comment.
        path = self._resolve_path(request, enforce_roots=False)
        pattern = request.arguments.get("pattern")

        if not isinstance(pattern, str) or not pattern.strip():
            raise InvalidFilesystemArgumentError(
                "request.arguments['pattern'] must be a non-empty "
                "string."
            )

        recursive = bool(
            request.arguments.get("recursive", self._default_search_recursive)
        )

        result = operations.search(path, pattern=pattern, recursive=recursive)

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_copy(self, request: ToolRequest) -> ToolResponse:
        self._security.require_write()

        # The source is only read from - permitted anywhere, matching
        # every other read-only operation. Only the destination, which
        # is written to, is confined to `allowed_roots`.
        source = self._resolve_path(request, "source", enforce_roots=False)
        destination = self._resolve_path(
            request, "destination", operation=WorkspaceOperation.WRITE
        )
        overwrite = bool(request.arguments.get("overwrite", False))

        result = operations.copy(source, destination, overwrite=overwrite)

        return ToolResponse(
            result=result,
            attributes={"source": str(source), "destination": str(destination)},
        )

    def _execute_move(self, request: ToolRequest) -> ToolResponse:
        self._security.require_write()
        # A move removes the source location entirely (unlike copy),
        # which is semantically a deletion - so it must additionally
        # respect `allow_delete`, and both endpoints are confined to
        # `allowed_roots` (unlike copy's read-only source).
        self._security.require_delete()

        source = self._resolve_path(request, "source", operation=WorkspaceOperation.DELETE)
        destination = self._resolve_path(
            request, "destination", operation=WorkspaceOperation.WRITE
        )
        overwrite = bool(request.arguments.get("overwrite", False))

        result = operations.move(source, destination, overwrite=overwrite)

        return ToolResponse(
            result=result,
            attributes={"source": str(source), "destination": str(destination)},
        )

    def _execute_delete(self, request: ToolRequest) -> ToolResponse:
        self._security.require_delete()

        path = self._resolve_path(request, operation=WorkspaceOperation.DELETE)
        recursive = bool(request.arguments.get("recursive", False))

        result = operations.delete(path, recursive=recursive)

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_mkdir(self, request: ToolRequest) -> ToolResponse:
        self._security.require_write()

        path = self._resolve_path(request, operation=WorkspaceOperation.WRITE)
        parents = bool(request.arguments.get("parents", True))
        exist_ok = bool(request.arguments.get("exist_ok", True))

        result = operations.mkdir(path, parents=parents, exist_ok=exist_ok)

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_exists(self, request: ToolRequest) -> ToolResponse:
        # Read-only - see _execute_read()'s comment.
        path = self._resolve_path(request, enforce_roots=False)

        result = operations.exists(path)

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_info(self, request: ToolRequest) -> ToolResponse:
        # Read-only - see _execute_read()'s comment.
        path = self._resolve_path(request, enforce_roots=False)

        result = operations.info(path)

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_walk(self, request: ToolRequest) -> ToolResponse:
        # Read-only - see _execute_read()'s comment.
        path = self._resolve_path(request, enforce_roots=False)

        raw_max_entries: Any = request.arguments.get(
            "max_entries", self._max_walk_entries
        )
        max_entries = min(int(raw_max_entries), self._max_walk_entries)

        result = operations.walk(path, max_entries=max_entries)

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_permissions(self, request: ToolRequest) -> ToolResponse:
        # Read-only - see _execute_read()'s comment.
        path = self._resolve_path(request, enforce_roots=False)

        result = operations.permissions(path)

        return ToolResponse(result=result, attributes={"path": str(path)})

    def _execute_watch(self, request: ToolRequest) -> ToolResponse:
        # Read-only (observes for changes; never mutates) - see
        # _execute_read()'s comment.
        path = self._resolve_path(request, enforce_roots=False)

        raw_interval: Any = request.arguments.get(
            "interval_seconds", self._watch_poll_interval_seconds
        )
        raw_duration: Any = request.arguments.get(
            "duration_seconds", self._watch_max_duration_seconds
        )

        interval_seconds = max(float(raw_interval), 0.1)
        duration_seconds = min(
            float(raw_duration), self._watch_max_duration_seconds
        )

        result = operations.watch(
            path,
            interval_seconds=interval_seconds,
            duration_seconds=duration_seconds,
        )

        return ToolResponse(result=result, attributes={"path": str(path)})
