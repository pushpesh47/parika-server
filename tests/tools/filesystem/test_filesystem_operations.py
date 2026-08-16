"""
Unit tests for `parika.tools.filesystem.operations`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.tools.filesystem import operations
from parika.tools.filesystem.exceptions import (
    FilesystemAlreadyExistsError,
    FilesystemPathNotFoundError,
    InvalidFilesystemArgumentError,
)


class TestReadWrite:
    def test_write_then_read(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"

        result = operations.write(target, content="hello")
        assert result["bytes_written"] == 5
        assert target.read_text() == "hello"

        read_result = operations.read(target)
        assert read_result["content"] == "hello"

    def test_write_is_atomic_no_temp_file_left_behind(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "a.txt"
        operations.write(target, content="hello")

        entries = list(tmp_path.iterdir())
        assert entries == [target]

    def test_append_mode(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        operations.write(target, content="hello ")
        operations.write(target, content="world", append=True)

        assert target.read_text() == "hello world"

    def test_write_without_create_parents_raises_when_missing(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "missing" / "a.txt"

        with pytest.raises(FilesystemPathNotFoundError):
            operations.write(target, content="x", create_parents=False)

    def test_read_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FilesystemPathNotFoundError):
            operations.read(tmp_path / "missing.txt")

    def test_read_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidFilesystemArgumentError):
            operations.read(tmp_path)


class TestBinaryReadWrite:
    def test_binary_write_then_binary_read_round_trip(
        self, tmp_path: Path
    ) -> None:
        import base64

        target = tmp_path / "image.bin"
        raw_bytes = b"\x89PNG\r\n\x1a\n\x00\x01\x02\xff"

        write_result = operations.write(
            target,
            content_base64=base64.b64encode(raw_bytes).decode("ascii"),
            binary=True,
        )
        assert write_result["bytes_written"] == len(raw_bytes)
        assert target.read_bytes() == raw_bytes

        read_result = operations.read(target, binary=True)
        assert read_result["encoding"] == "base64"
        assert read_result["size"] == len(raw_bytes)
        assert base64.b64decode(read_result["content_base64"]) == raw_bytes

    def test_binary_write_is_atomic_no_temp_file_left_behind(
        self, tmp_path: Path
    ) -> None:
        import base64

        target = tmp_path / "a.bin"
        operations.write(
            target,
            content_base64=base64.b64encode(b"\x00\x01").decode("ascii"),
            binary=True,
        )

        entries = list(tmp_path.iterdir())
        assert entries == [target]

    def test_binary_append_mode(self, tmp_path: Path) -> None:
        import base64

        target = tmp_path / "a.bin"
        operations.write(
            target,
            content_base64=base64.b64encode(b"\x01\x02").decode("ascii"),
            binary=True,
        )
        operations.write(
            target,
            content_base64=base64.b64encode(b"\x03\x04").decode("ascii"),
            binary=True,
            append=True,
        )

        assert target.read_bytes() == b"\x01\x02\x03\x04"

    def test_text_write_still_defaults_to_text_mode(self, tmp_path: Path) -> None:
        """
        `binary=False` (the default) must produce byte-for-byte
        identical output to the pre-existing text-only behavior.
        """

        target = tmp_path / "a.txt"
        result = operations.write(target, content="héllo")

        assert target.read_bytes() == "héllo".encode("utf-8")
        assert result["bytes_written"] == len("héllo".encode("utf-8"))


class TestListSearchWalk:
    def test_list_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("1")
        (tmp_path / "b.py").write_text("2")

        result = operations.list_directory(tmp_path)
        names = sorted(entry["name"] for entry in result["entries"])
        assert names == ["a.txt", "b.py"]

    def test_list_with_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("1")
        (tmp_path / "b.py").write_text("2")

        result = operations.list_directory(tmp_path, pattern="*.py")
        names = [entry["name"] for entry in result["entries"]]
        assert names == ["b.py"]

    def test_search_recursive(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "target.py").write_text("x")
        (tmp_path / "other.txt").write_text("y")

        result = operations.search(tmp_path, pattern="*.py", recursive=True)
        assert len(result["matches"]) == 1
        assert result["matches"][0].endswith("target.py")

    def test_search_non_recursive_ignores_subdirectories(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "target.py").write_text("x")

        result = operations.search(tmp_path, pattern="*.py", recursive=False)
        assert result["matches"] == []

    def test_walk_lists_files_and_directories(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file.txt").write_text("x")

        result = operations.walk(tmp_path)
        paths = {entry["path"] for entry in result["entries"]}
        assert str(tmp_path / "sub") in paths
        assert str(tmp_path / "sub" / "file.txt") in paths
        assert result["truncated"] is False

    def test_walk_respects_max_entries(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"f{i}.txt").write_text("x")

        result = operations.walk(tmp_path, max_entries=2)
        assert len(result["entries"]) <= 2
        assert result["truncated"] is True


class TestCopyMoveDelete:
    def test_copy_file(self, tmp_path: Path) -> None:
        source = tmp_path / "a.txt"
        source.write_text("content")
        destination = tmp_path / "b.txt"

        operations.copy(source, destination)

        assert destination.read_text() == "content"
        assert source.exists()

    def test_copy_refuses_overwrite_by_default(self, tmp_path: Path) -> None:
        source = tmp_path / "a.txt"
        source.write_text("content")
        destination = tmp_path / "b.txt"
        destination.write_text("existing")

        with pytest.raises(FilesystemAlreadyExistsError):
            operations.copy(source, destination)

    def test_copy_overwrite_true_replaces(self, tmp_path: Path) -> None:
        source = tmp_path / "a.txt"
        source.write_text("content")
        destination = tmp_path / "b.txt"
        destination.write_text("existing")

        operations.copy(source, destination, overwrite=True)
        assert destination.read_text() == "content"

    def test_move_file(self, tmp_path: Path) -> None:
        source = tmp_path / "a.txt"
        source.write_text("content")
        destination = tmp_path / "b.txt"

        operations.move(source, destination)

        assert destination.read_text() == "content"
        assert not source.exists()

    def test_delete_file(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("content")

        operations.delete(target)

        assert not target.exists()

    def test_delete_non_empty_directory_requires_recursive(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "child.txt").write_text("x")

        with pytest.raises(InvalidFilesystemArgumentError):
            operations.delete(tmp_path, recursive=False)

        operations.delete(tmp_path, recursive=True)
        assert not tmp_path.exists()


class TestMkdirExistsInfoPermissions:
    def test_mkdir_creates_nested_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c"

        operations.mkdir(target)

        assert target.is_dir()

    def test_exists_true_and_false(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"

        assert operations.exists(target)["exists"] is False

        target.write_text("x")
        assert operations.exists(target)["exists"] is True

    def test_info_reports_size_and_type(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("hello")

        result = operations.info(target)
        assert result["size"] == 5
        assert result["is_file"] is True
        assert result["is_dir"] is False

    def test_permissions_reports_access(self, tmp_path: Path) -> None:
        target = tmp_path / "a.txt"
        target.write_text("hello")

        result = operations.permissions(target)
        assert result["readable"] is True


class TestWatch:
    def test_watch_reports_no_changes_when_nothing_changes(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "a.txt"
        target.write_text("hello")

        fake_time = [0.0]

        def fake_now() -> float:
            return fake_time[0]

        def fake_sleep(seconds: float) -> None:
            fake_time[0] += seconds

        result = operations.watch(
            tmp_path,
            interval_seconds=1.0,
            duration_seconds=3.0,
            sleep=fake_sleep,
            now=fake_now,
        )

        assert result["changes"] == []

    def test_watch_detects_a_new_file(self, tmp_path: Path) -> None:
        fake_time = [0.0]

        def fake_now() -> float:
            return fake_time[0]

        created = {"done": False}

        def fake_sleep(seconds: float) -> None:
            fake_time[0] += seconds

            if not created["done"]:
                (tmp_path / "new.txt").write_text("new")
                created["done"] = True

        result = operations.watch(
            tmp_path,
            interval_seconds=1.0,
            duration_seconds=3.0,
            sleep=fake_sleep,
            now=fake_now,
        )

        events = {change["event"] for change in result["changes"]}
        assert "created" in events
