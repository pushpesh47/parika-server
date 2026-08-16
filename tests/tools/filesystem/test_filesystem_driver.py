"""
Unit tests for FilesystemToolDriver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.tools.filesystem.driver import FilesystemToolDriver
from parika.tools.filesystem.exceptions import (
    FilesystemOperationNotPermittedError,
    InvalidFilesystemArgumentError,
    PathNotAllowedError,
)
from parika.tools.filesystem.manifest import FilesystemOperation
from parika.tools.filesystem.security import PathSecurity, PathSecurityConfig


def _driver(
    operation: FilesystemOperation,
    tmp_path: Path,
    *,
    allow_write: bool = True,
    allow_delete: bool = True,
) -> FilesystemToolDriver:
    security = PathSecurity(
        PathSecurityConfig(
            allowed_roots=(tmp_path,),
            allow_write=allow_write,
            allow_delete=allow_delete,
        )
    )
    return FilesystemToolDriver(operation, security=security)


class TestReadWrite:
    def test_write_then_read(self, tmp_path: Path) -> None:
        target = str(tmp_path / "a.txt")

        write_driver = _driver(FilesystemOperation.WRITE, tmp_path)
        write_driver.execute(
            ToolRequest(arguments={"path": target, "content": "hi"})
        )

        read_driver = _driver(FilesystemOperation.READ, tmp_path)
        response = read_driver.execute(ToolRequest(arguments={"path": target}))

        assert response.result["content"] == "hi"

    def test_write_disabled_raises(self, tmp_path: Path) -> None:
        driver = _driver(FilesystemOperation.WRITE, tmp_path, allow_write=False)

        with pytest.raises(FilesystemOperationNotPermittedError):
            driver.execute(
                ToolRequest(
                    arguments={"path": str(tmp_path / "a.txt"), "content": "x"}
                )
            )

    def test_write_rejects_non_string_content(self, tmp_path: Path) -> None:
        driver = _driver(FilesystemOperation.WRITE, tmp_path)

        with pytest.raises(InvalidFilesystemArgumentError):
            driver.execute(
                ToolRequest(
                    arguments={"path": str(tmp_path / "a.txt"), "content": 5}
                )
            )

    def test_read_path_outside_root_is_allowed(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """
        Paths outside `allowed_roots` remain accessible in READ ONLY
        mode -- only mutating operations are confined to
        `allowed_roots`. See `PathSecurity.resolve()`'s docstring.
        """

        outside_dir = tmp_path_factory.mktemp("outside")
        outside_file = outside_dir / "readable.txt"
        outside_file.write_text("outside content")

        driver = _driver(FilesystemOperation.READ, tmp_path)

        response = driver.execute(
            ToolRequest(arguments={"path": str(outside_file)})
        )

        assert response.result["content"] == "outside content"

    def test_read_succeeds_even_when_no_roots_are_configured_at_all(
        self, tmp_path: Path
    ) -> None:
        """
        Reads are always allowed, any resolvable host path,
        unconditionally - independent of `allowed_roots`/
        `trusted_workspaces` configuration entirely. Only mutating/
        destructive operations remain deny-by-default with zero
        configured roots (see `TestPermissionGates`/write-class tests
        elsewhere in this module).
        """

        target = tmp_path / "hostname_stand_in.txt"
        target.write_text("example")

        security = PathSecurity(PathSecurityConfig(allowed_roots=()))
        driver = FilesystemToolDriver(FilesystemOperation.READ, security=security)

        response = driver.execute(ToolRequest(arguments={"path": str(target)}))

        assert response.result["content"] == "example"

    def test_write_path_outside_root_raises(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """
        Unlike reads, writes remain confined to `allowed_roots`.
        """

        outside_dir = tmp_path_factory.mktemp("outside")
        driver = _driver(FilesystemOperation.WRITE, tmp_path)

        with pytest.raises(PathNotAllowedError):
            driver.execute(
                ToolRequest(
                    arguments={
                        "path": str(outside_dir / "a.txt"),
                        "content": "x",
                    }
                )
            )


class TestBinaryReadWrite:
    def test_binary_write_then_binary_read(self, tmp_path: Path) -> None:
        import base64

        target = str(tmp_path / "a.bin")
        raw_bytes = b"\x00\x01\xfe\xff"
        content_base64 = base64.b64encode(raw_bytes).decode("ascii")

        write_driver = _driver(FilesystemOperation.WRITE, tmp_path)
        write_driver.execute(
            ToolRequest(
                arguments={
                    "path": target,
                    "binary": True,
                    "content_base64": content_base64,
                }
            )
        )

        read_driver = _driver(FilesystemOperation.READ, tmp_path)
        response = read_driver.execute(
            ToolRequest(arguments={"path": target, "binary": True})
        )

        assert base64.b64decode(response.result["content_base64"]) == raw_bytes

    def test_binary_write_requires_content_base64(self, tmp_path: Path) -> None:
        driver = _driver(FilesystemOperation.WRITE, tmp_path)

        with pytest.raises(InvalidFilesystemArgumentError):
            driver.execute(
                ToolRequest(
                    arguments={"path": str(tmp_path / "a.bin"), "binary": True}
                )
            )


class TestDeleteGate:
    def test_delete_disabled_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("x")

        driver = _driver(
            FilesystemOperation.DELETE, tmp_path, allow_delete=False
        )

        with pytest.raises(FilesystemOperationNotPermittedError):
            driver.execute(ToolRequest(arguments={"path": str(target)}))

    def test_delete_enabled_removes_file(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("x")

        driver = _driver(FilesystemOperation.DELETE, tmp_path)
        driver.execute(ToolRequest(arguments={"path": str(target)}))

        assert not target.exists()


class TestCopyMove:
    def test_copy(self, tmp_path: Path) -> None:
        source = tmp_path / "a.txt"
        source.write_text("x")
        destination = tmp_path / "b.txt"

        driver = _driver(FilesystemOperation.COPY, tmp_path)
        response = driver.execute(
            ToolRequest(
                arguments={"source": str(source), "destination": str(destination)}
            )
        )

        assert destination.read_text() == "x"
        assert response.attributes["destination"] == str(destination)

    def test_move(self, tmp_path: Path) -> None:
        source = tmp_path / "a.txt"
        source.write_text("x")
        destination = tmp_path / "b.txt"

        driver = _driver(FilesystemOperation.MOVE, tmp_path)
        driver.execute(
            ToolRequest(
                arguments={"source": str(source), "destination": str(destination)}
            )
        )

        assert destination.exists()
        assert not source.exists()

    def test_copy_source_outside_root_is_allowed(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """
        Copy's source is read-only, so it may live outside
        `allowed_roots`; only the destination is confined.
        """

        outside_dir = tmp_path_factory.mktemp("outside")
        source = outside_dir / "a.txt"
        source.write_text("x")
        destination = tmp_path / "b.txt"

        driver = _driver(FilesystemOperation.COPY, tmp_path)
        driver.execute(
            ToolRequest(
                arguments={"source": str(source), "destination": str(destination)}
            )
        )

        assert destination.read_text() == "x"

    def test_copy_destination_outside_root_raises(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        source = tmp_path / "a.txt"
        source.write_text("x")
        outside_dir = tmp_path_factory.mktemp("outside")

        driver = _driver(FilesystemOperation.COPY, tmp_path)

        with pytest.raises(PathNotAllowedError):
            driver.execute(
                ToolRequest(
                    arguments={
                        "source": str(source),
                        "destination": str(outside_dir / "b.txt"),
                    }
                )
            )

    def test_move_source_outside_root_raises(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """
        Unlike copy, move mutates (removes) its source, so both
        endpoints are confined to `allowed_roots`.
        """

        outside_dir = tmp_path_factory.mktemp("outside")
        source = outside_dir / "a.txt"
        source.write_text("x")

        driver = _driver(FilesystemOperation.MOVE, tmp_path)

        with pytest.raises(PathNotAllowedError):
            driver.execute(
                ToolRequest(
                    arguments={
                        "source": str(source),
                        "destination": str(tmp_path / "b.txt"),
                    }
                )
            )

    def test_move_requires_allow_delete(self, tmp_path: Path) -> None:
        """
        A move deletes its source location, so it must respect
        `allow_delete` in addition to `allow_write`.
        """

        source = tmp_path / "a.txt"
        source.write_text("x")

        driver = _driver(FilesystemOperation.MOVE, tmp_path, allow_delete=False)

        with pytest.raises(FilesystemOperationNotPermittedError):
            driver.execute(
                ToolRequest(
                    arguments={
                        "source": str(source),
                        "destination": str(tmp_path / "b.txt"),
                    }
                )
            )


class TestListSearchWalkInfoExistsPermissions:
    def test_list(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("1")

        driver = _driver(FilesystemOperation.LIST, tmp_path)
        response = driver.execute(ToolRequest(arguments={"path": str(tmp_path)}))

        assert len(response.result["entries"]) == 1

    def test_search_requires_pattern(self, tmp_path: Path) -> None:
        driver = _driver(FilesystemOperation.SEARCH, tmp_path)

        with pytest.raises(InvalidFilesystemArgumentError):
            driver.execute(ToolRequest(arguments={"path": str(tmp_path)}))

    def test_walk_clamps_max_entries_to_configured_ceiling(
        self, tmp_path: Path
    ) -> None:
        for i in range(5):
            (tmp_path / f"f{i}.txt").write_text("x")

        security = PathSecurity(PathSecurityConfig(allowed_roots=(tmp_path,)))
        driver = FilesystemToolDriver(
            FilesystemOperation.WALK, security=security, max_walk_entries=2
        )

        response = driver.execute(
            ToolRequest(arguments={"path": str(tmp_path), "max_entries": 100})
        )

        assert len(response.result["entries"]) <= 2

    def test_info(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("hello")

        driver = _driver(FilesystemOperation.INFO, tmp_path)
        response = driver.execute(ToolRequest(arguments={"path": str(target)}))

        assert response.result["size"] == 5

    def test_exists(self, tmp_path: Path) -> None:
        driver = _driver(FilesystemOperation.EXISTS, tmp_path)
        response = driver.execute(
            ToolRequest(arguments={"path": str(tmp_path / "missing.txt")})
        )

        assert response.result["exists"] is False

    def test_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("hello")

        driver = _driver(FilesystemOperation.PERMISSIONS, tmp_path)
        response = driver.execute(ToolRequest(arguments={"path": str(target)}))

        assert response.result["readable"] is True

    def test_exists_outside_root_is_allowed(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        outside_dir = tmp_path_factory.mktemp("outside")
        target = outside_dir / "a.txt"
        target.write_text("hello")

        driver = _driver(FilesystemOperation.EXISTS, tmp_path)
        response = driver.execute(ToolRequest(arguments={"path": str(target)}))

        assert response.result["exists"] is True

    def test_list_outside_root_is_allowed(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        outside_dir = tmp_path_factory.mktemp("outside")
        (outside_dir / "a.txt").write_text("1")

        driver = _driver(FilesystemOperation.LIST, tmp_path)
        response = driver.execute(
            ToolRequest(arguments={"path": str(outside_dir)})
        )

        assert len(response.result["entries"]) == 1


class TestWatch:
    def test_watch_clamps_duration_to_configured_ceiling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        security = PathSecurity(PathSecurityConfig(allowed_roots=(tmp_path,)))
        driver = FilesystemToolDriver(
            FilesystemOperation.WATCH,
            security=security,
            watch_max_duration_seconds=2.0,
        )

        captured: dict[str, float] = {}

        def _fake_watch(path, **kwargs):  # noqa: ANN001, ANN003
            captured["duration_seconds"] = kwargs["duration_seconds"]
            return {"path": str(path), "changes": [], **kwargs}

        import parika.tools.filesystem.driver as driver_module

        monkeypatch.setattr(driver_module.operations, "watch", _fake_watch)

        driver.execute(
            ToolRequest(
                arguments={"path": str(tmp_path), "duration_seconds": 999}
            )
        )

        assert captured["duration_seconds"] == 2.0
