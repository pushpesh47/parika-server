"""
Unit tests for RuntimeTrustWriter.
"""

from __future__ import annotations

import logging
from pathlib import Path

import tomlkit

from parika.core.permission_manager.workspace_trust_store import RuntimeTrustWriter


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


def _writer(runtime_toml_path: Path) -> RuntimeTrustWriter:
    return RuntimeTrustWriter(
        runtime_toml_path=runtime_toml_path,
        logger=_FakeLogger(),  # type: ignore[arg-type]
    )


class TestAddTrustedWorkspace:
    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        runtime_toml_path = tmp_path / "config" / "runtime.toml"
        writer = _writer(runtime_toml_path)

        writer.add_trusted_workspace(Path("/some/workspace"))

        assert runtime_toml_path.exists()
        document = tomlkit.parse(runtime_toml_path.read_text())
        assert list(document["filesystem"]["trusted_workspaces"]) == [
            "/some/workspace"
        ]

    def test_does_not_duplicate_an_existing_entry(self, tmp_path: Path) -> None:
        runtime_toml_path = tmp_path / "runtime.toml"
        writer = _writer(runtime_toml_path)

        writer.add_trusted_workspace(Path("/some/workspace"))
        writer.add_trusted_workspace(Path("/some/workspace"))

        document = tomlkit.parse(runtime_toml_path.read_text())
        assert list(document["filesystem"]["trusted_workspaces"]) == [
            "/some/workspace"
        ]

    def test_appends_to_an_existing_array(self, tmp_path: Path) -> None:
        runtime_toml_path = tmp_path / "runtime.toml"
        runtime_toml_path.write_text(
            '[filesystem]\ntrusted_workspaces = ["/existing"]\n'
        )
        writer = _writer(runtime_toml_path)

        writer.add_trusted_workspace(Path("/new/workspace"))

        document = tomlkit.parse(runtime_toml_path.read_text())
        assert list(document["filesystem"]["trusted_workspaces"]) == [
            "/existing",
            "/new/workspace",
        ]

    def test_preserves_existing_unrelated_content_and_comments(
        self, tmp_path: Path
    ) -> None:
        runtime_toml_path = tmp_path / "runtime.toml"
        runtime_toml_path.write_text(
            "# Auto-managed runtime configuration.\n"
            "[application]\n"
            "environment = \"development\"\n"
        )
        writer = _writer(runtime_toml_path)

        writer.add_trusted_workspace(Path("/some/workspace"))

        content = runtime_toml_path.read_text()
        assert "# Auto-managed runtime configuration." in content
        assert 'environment = "development"' in content

        document = tomlkit.parse(content)
        assert list(document["filesystem"]["trusted_workspaces"]) == [
            "/some/workspace"
        ]

    def test_write_is_atomic_no_temp_file_left_behind(self, tmp_path: Path) -> None:
        runtime_toml_path = tmp_path / "runtime.toml"
        writer = _writer(runtime_toml_path)

        writer.add_trusted_workspace(Path("/some/workspace"))

        entries = list(tmp_path.iterdir())
        assert entries == [runtime_toml_path]

    def test_creates_parent_directory_if_missing(self, tmp_path: Path) -> None:
        runtime_toml_path = tmp_path / "nested" / "config" / "runtime.toml"
        writer = _writer(runtime_toml_path)

        writer.add_trusted_workspace(Path("/some/workspace"))

        assert runtime_toml_path.exists()
