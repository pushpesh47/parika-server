"""
Unit tests for ProjectDetectorRegistry and its default detectors.
"""

from __future__ import annotations

from pathlib import Path

from parika.modules.repository_intelligence.indexing.project_detector import (
    ProjectDetectorRegistry,
)


def test_detects_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\n# pytest ruff\n", encoding="utf-8"
    )

    summaries = ProjectDetectorRegistry().detect(tmp_path)

    assert len(summaries) == 1
    assert summaries[0].ecosystem == "python"
    assert summaries[0].test_framework == "pytest"
    assert summaries[0].linter == "ruff"


def test_detects_node_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"react": "^18.0.0"}, "devDependencies": {"jest": "^1.0.0"}}',
        encoding="utf-8",
    )

    summaries = ProjectDetectorRegistry().detect(tmp_path)

    assert summaries[0].ecosystem == "node"
    assert summaries[0].framework == "react"
    assert summaries[0].test_framework == "jest"


def test_detects_go_project(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/x\n", encoding="utf-8")

    summaries = ProjectDetectorRegistry().detect(tmp_path)

    assert summaries[0].ecosystem == "go"
    assert summaries[0].test_framework == "go test"


def test_detects_csharp_project_by_suffix(tmp_path: Path) -> None:
    (tmp_path / "App.csproj").write_text("<Project></Project>", encoding="utf-8")

    summaries = ProjectDetectorRegistry().detect(tmp_path)

    assert summaries[0].ecosystem == "csharp"


def test_detects_multiple_nested_projects(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")

    summaries = ProjectDetectorRegistry().detect(tmp_path)
    ecosystems = {summary.ecosystem for summary in summaries}

    assert ecosystems == {"python", "node"}


def test_no_manifest_returns_empty(tmp_path: Path) -> None:
    summaries = ProjectDetectorRegistry().detect(tmp_path)
    assert summaries == ()
