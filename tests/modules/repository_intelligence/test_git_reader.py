"""
Unit tests for GitReader, using a fake ToolManager -- never a real Git
repository, and never any command beyond the fixed, read-only set.
"""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

from pathlib import Path

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.modules.repository_intelligence.repository.git_reader import GitReader


class _FakeToolManager:
    def __init__(self, responses: dict[str, dict]) -> None:
        self._responses = responses
        self.calls: list[list[str]] = []

    def execute(self, tool_id: str, request: ToolRequest) -> ToolResponse:
        command = list(request.arguments["command"])
        self.calls.append(command)
        key = command[1]  # "rev-parse" | "remote" | "log"
        return ToolResponse(result=self._responses.get(key, {"exit_code": 1}))


def test_current_branch_returns_trimmed_output() -> None:
    fake = _FakeToolManager(
        {"rev-parse": {"stdout": "main\n", "exit_code": 0}}
    )
    reader = GitReader(fake)  # type: ignore[arg-type]

    assert reader.current_branch(Path("/repo")) == "main"
    assert fake.calls[0] == ["git", "rev-parse", "--abbrev-ref", "HEAD"]


def test_remote_url_returns_none_on_failure() -> None:
    fake = _FakeToolManager({"remote": {"exit_code": 1}})
    reader = GitReader(fake)  # type: ignore[arg-type]

    assert reader.remote_url(Path("/repo")) is None


def test_recent_commits_splits_lines() -> None:
    fake = _FakeToolManager(
        {"log": {"stdout": "abc123 First\nabc124 Second\n", "exit_code": 0}}
    )
    reader = GitReader(fake)  # type: ignore[arg-type]

    commits = reader.recent_commits(Path("/repo"), limit=2)
    assert commits == ("abc123 First", "abc124 Second")
    assert fake.calls[0] == ["git", "log", "-n2", "--format=%h %s"]


def test_never_issues_a_mutating_command() -> None:
    """
    GitReader's API surface is a fixed, closed set of three read-only
    queries -- this test pins that invariant down.
    """

    allowed_subcommands = {"rev-parse", "remote", "log"}
    fake = _FakeToolManager({})
    reader = GitReader(fake)  # type: ignore[arg-type]

    reader.current_branch(Path("/repo"))
    reader.remote_url(Path("/repo"))
    reader.recent_commits(Path("/repo"))

    for command in fake.calls:
        assert command[0] == "git"
        assert command[1] in allowed_subcommands
