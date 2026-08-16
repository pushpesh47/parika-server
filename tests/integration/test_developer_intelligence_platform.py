"""
Integration tests for the Developer Intelligence Platform: builds a
real `ParikaRuntime` (via `build_default_runtime()`, exactly as the
CLI does) and exercises the Coding Tool, Repository Intelligence, and
Coding Agent Modules together, through their public Capabilities --
never by reaching into private attributes of unrelated Core
components.

Ollama is never started for these tests (`discover_ollama_models=
False`); the `coding.execute_task`/`coding.plan_change` test below
therefore exercises real Planner/TaskManager/CapabilityExecutor/Brain
wiring up to the point a Provider model would be required, and asserts
the failure is reported gracefully through `BrainResponse` rather than
raised or crashing -- exactly Brain's documented contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.brain.brain_request import BrainRequest
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.planner.goal import Goal
from parika.core.tool_manager.request import ToolRequest
from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.modules.coding.manifest import CODING_MODULE_ID
from parika.modules.repository_intelligence.manifest import (
    REPOSITORY_INTELLIGENCE_MODULE_ID,
)


@pytest.fixture()
def runtime(tmp_path: Path):
    instance = build_default_runtime(
        load_modules=True,
        discover_ollama_models=False,
        discover_comfyui_models=False,
        data_directory=tmp_path / "data",
    )
    yield instance
    shutdown_runtime(instance)


@pytest.fixture()
def sample_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    repo = workspace / "sample_repo"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "README.md").write_text(
        "# Sample Repo\n\nA repository about widgets and gadgets.\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    (repo / "widgets.py").write_text(
        '"""Widgets module."""\n\n\n'
        "class Widget:\n"
        '    """A widget."""\n\n\n'
        "def build_widget():\n"
        '    """Build a widget."""\n'
        "    return Widget()\n",
        encoding="utf-8",
    )
    return workspace


def test_every_developer_intelligence_module_is_active(runtime) -> None:
    module_ids = {module.id for module in runtime.module_manager.get_active()}

    assert CODING_MODULE_ID in module_ids
    assert REPOSITORY_INTELLIGENCE_MODULE_ID in module_ids
    assert "coding_agent" in module_ids


def test_repository_intelligence_indexes_and_coding_tool_serves_symbols(
    runtime, sample_workspace: Path
) -> None:
    repository_intelligence = runtime.module_manager.get(
        REPOSITORY_INTELLIGENCE_MODULE_ID
    ).driver

    ran = repository_intelligence.index_workspace(str(sample_workspace))
    assert ran is True

    response = runtime.tool_manager.execute(
        "tool.coding_symbols",
        ToolRequest(arguments={"path": str(sample_workspace / "sample_repo" / "widgets.py")}),
    )
    names = {symbol["qualified_name"] for symbol in response.result}
    assert "widgets.Widget" in names
    assert "widgets.build_widget" in names


def test_readme_is_searchable_through_knowledge_manager(
    runtime, sample_workspace: Path
) -> None:
    repository_intelligence = runtime.module_manager.get(
        REPOSITORY_INTELLIGENCE_MODULE_ID
    ).driver
    repository_intelligence.index_workspace(str(sample_workspace))

    results = runtime.knowledge_manager.search(
        SearchQuery(text="widgets and gadgets", limit=10)
    )
    assert len(results) >= 1


def test_project_awareness_detects_python_project(
    runtime, sample_workspace: Path
) -> None:
    repository_intelligence = runtime.module_manager.get(
        REPOSITORY_INTELLIGENCE_MODULE_ID
    ).driver

    snapshot = repository_intelligence.engine.discover(str(sample_workspace))
    repository = snapshot.repositories[0]

    assert repository.is_git_repository is True
    assert repository.readme_path is not None
    assert any(project.ecosystem == "python" for project in repository.projects)


def test_coding_search_finds_indexed_symbols_end_to_end(
    runtime, sample_workspace: Path
) -> None:
    repository_intelligence = runtime.module_manager.get(
        REPOSITORY_INTELLIGENCE_MODULE_ID
    ).driver
    repository_intelligence.index_workspace(str(sample_workspace))

    response = runtime.tool_manager.execute(
        "tool.coding_search", ToolRequest(arguments={"query": "widget"})
    )
    names = {symbol["qualified_name"] for symbol in response.result}
    assert "widgets.Widget" in names


def test_coding_execute_task_goal_reaches_planner_and_fails_gracefully(runtime) -> None:
    """
    With no Ollama provider registered/available, submitting a Goal
    for `coding.execute_task` must still be planned and executed
    through the real, unmodified Brain/Planner/TaskManager/
    CapabilityExecutor pipeline -- the Coding Agent's own decomposition
    step (`coding.plan_change`, an LLM-category Capability) fails
    because no Provider model is available, and Brain reports that
    failure through `BrainResponse` rather than raising or crashing.
    """

    goal = Goal(
        id="test-goal",
        capability_id="coding.execute_task",
        inputs={"instruction": "Add input validation to main()"},
    )

    response = runtime.brain.handle(BrainRequest(goals=(goal,)))

    assert not response.succeeded
    assert len(response.results) == 1
    assert not response.results[0].succeeded
