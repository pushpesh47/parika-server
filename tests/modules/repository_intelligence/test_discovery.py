"""
Unit tests for discover_workspace().
"""

from __future__ import annotations

from pathlib import Path

from parika.modules.repository_intelligence.workspace.discovery import (
    discover_workspace,
)


def test_discovers_git_repository(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "README.md").write_text("# My Repo\n", encoding="utf-8")

    snapshot = discover_workspace(tmp_path)

    assert len(snapshot.repositories) == 1
    repository = snapshot.repositories[0]
    assert repository.root == repo
    assert repository.is_git_repository is True
    assert repository.readme_path == repo / "README.md"


def test_bare_directory_without_git_is_still_treated_as_one_repository(
    tmp_path: Path,
) -> None:
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")

    snapshot = discover_workspace(tmp_path)

    assert len(snapshot.repositories) == 1
    assert snapshot.repositories[0].root == tmp_path
    assert snapshot.repositories[0].is_git_repository is False


def test_discovers_multiple_repositories(tmp_path: Path) -> None:
    for name in ("repo_a", "repo_b"):
        repo = tmp_path / name
        repo.mkdir()
        (repo / ".git").mkdir()

    snapshot = discover_workspace(tmp_path)

    roots = {repository.root for repository in snapshot.repositories}
    assert roots == {tmp_path / "repo_a", tmp_path / "repo_b"}


def test_ignored_directories_are_not_descended_into(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    nested_ignored = tmp_path / "node_modules" / "some_pkg"
    nested_ignored.mkdir(parents=True)
    (nested_ignored / ".git").mkdir()

    snapshot = discover_workspace(tmp_path)

    assert len(snapshot.repositories) == 1
    assert snapshot.repositories[0].root == tmp_path


def test_repository_includes_detected_projects(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    snapshot = discover_workspace(tmp_path)

    assert len(snapshot.repositories[0].projects) == 1
    assert snapshot.repositories[0].projects[0].ecosystem == "python"
