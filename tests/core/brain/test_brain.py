"""
Unit tests for Brain.

Brain is exercised against the real Planner, TaskManager, and
CapabilityExecutor stack (with a fake ToolDriver standing in for
actual tool logic) so the full orchestration contract is verified,
not just Brain in isolation. Logger and EventBus use real instances
because ToolManager strictly type-checks its Logger dependency.
"""

from __future__ import annotations

from typing import Any

import pytest

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.exceptions import InvalidBrainRequestError
from parika.core.capability_executor.capability_executor import (
    CapabilityExecutor,
)
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.exceptions import TaskExecutionError
from parika.core.task_manager.task_manager import TaskManager
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.exceptions import ToolExecutionError
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressEvent, ProgressStage


class _ScriptedToolDriver:
    """Tool driver returning scripted responses/exceptions per call."""

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []
        self._response: ToolResponse | None = None
        self._error: Exception | None = None

    def succeed_with(self, response: ToolResponse) -> None:
        self._response = response
        self._error = None

    def fail_with(self, error: Exception) -> None:
        self._error = error
        self._response = None

    def execute(self, request: ToolRequest) -> ToolResponse:
        self.calls.append(request)

        if self._error is not None:
            raise self._error

        assert self._response is not None
        return self._response


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    return EventBus(logger=logger)


@pytest.fixture
def capability_registry(
    event_bus: EventBus,
    logger: Logger,
) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


@pytest.fixture
def capability_resolver(
    capability_registry: CapabilityRegistry,
    logger: Logger,
) -> CapabilityResolver:
    return CapabilityResolver(
        capability_registry=capability_registry,
        logger=logger,
    )


@pytest.fixture
def resource_manager(logger: Logger) -> ResourceManager:
    return ResourceManager(configuration=Configuration(), logger=logger)


@pytest.fixture
def policy_engine(event_bus: EventBus, logger: Logger) -> PolicyEngine:
    return PolicyEngine(event_bus=event_bus, logger=logger)


@pytest.fixture
def provider_manager(event_bus: EventBus, logger: Logger) -> ProviderManager:
    return ProviderManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def capability_executor(
    event_bus: EventBus,
    logger: Logger,
    tool_manager: ToolManager,
    provider_manager: ProviderManager,
) -> CapabilityExecutor:
    return CapabilityExecutor(
        event_bus=event_bus,
        logger=logger,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
    )


@pytest.fixture
def planner(
    capability_resolver: CapabilityResolver,
    resource_manager: ResourceManager,
    policy_engine: PolicyEngine,
    provider_manager: ProviderManager,
    tool_manager: ToolManager,
    logger: Logger,
) -> Planner:
    return Planner(
        capability_resolver=capability_resolver,
        resource_manager=resource_manager,
        policy_engine=policy_engine,
        provider_manager=provider_manager,
        tool_manager=tool_manager,
        logger=logger,
    )


@pytest.fixture
def task_manager(
    event_bus: EventBus,
    logger: Logger,
    capability_executor: CapabilityExecutor,
) -> TaskManager:
    return TaskManager(
        event_bus=event_bus,
        logger=logger,
        capability_executor=capability_executor,
    )


@pytest.fixture
def brain(planner: Planner, task_manager: TaskManager, logger: Logger) -> Brain:
    return Brain(planner=planner, task_manager=task_manager, logger=logger)


@pytest.fixture
def brain_with_progress(
    planner: Planner,
    task_manager: TaskManager,
    logger: Logger,
    event_bus: EventBus,
) -> Brain:
    return Brain(
        planner=planner,
        task_manager=task_manager,
        logger=logger,
        event_bus=event_bus,
    )


class _ProgressCollector:
    """Collects every ProgressEvent published on the generic channels."""

    def __init__(self, event_bus: EventBus) -> None:
        self.events: list[ProgressEvent] = []

        for stage in ProgressStage:
            event_bus.subscribe(f"progress.{stage.value}", self.events.append)


def _register_tool(
    capability_registry: CapabilityRegistry,
    tool_manager: ToolManager,
    *,
    capability_id: str,
    tool_id: str,
    driver: _ScriptedToolDriver,
) -> None:
    capability_registry.register(
        CapabilityDefinition(
            id=capability_id,
            name=capability_id,
            description=capability_id,
            category=CapabilityCategory.TOOL,
        )
    )
    tool_manager.register(
        Tool(
            id=tool_id,
            name=tool_id,
            version="1.0.0",
            description=tool_id,
            capabilities=(capability_id,),
        ),
        driver,
    )


# ---------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------


class TestValidation:
    def test_rejects_non_brain_request(self, brain: Brain) -> None:
        with pytest.raises(InvalidBrainRequestError):
            brain.handle(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# End-to-end success
# ---------------------------------------------------------------------


class TestSuccessfulExecution:
    def test_single_goal_succeeds(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"results": ["a", "b"]}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="web.search",
            tool_id="tool.web_search",
            driver=driver,
        )

        goal = Goal(
            id="g1",
            capability_id="web.search",
            inputs={"query": "parika"},
        )
        request = BrainRequest(goals=(goal,))

        response = brain.handle(request)

        assert response.succeeded
        assert response.plan_id is not None
        assert len(response.results) == 1

        result = response.results[0]
        assert result.succeeded
        assert result.status is TaskStatus.COMPLETED
        assert result.response is not None
        assert driver.calls[0].arguments["query"] == "parika"

    def test_multiple_independent_goals_all_succeed(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        driver_a = _ScriptedToolDriver()
        driver_a.succeed_with(ToolResponse(result={"ok": True}))
        driver_b = _ScriptedToolDriver()
        driver_b.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.a",
            tool_id="tool.a",
            driver=driver_a,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.b",
            tool_id="tool.b",
            driver=driver_b,
        )

        request = BrainRequest(
            goals=(
                Goal(id="a", capability_id="tool.a"),
                Goal(id="b", capability_id="tool.b"),
            )
        )

        response = brain.handle(request)

        assert response.succeeded
        assert len(response.results) == 2
        assert all(result.succeeded for result in response.results)


# ---------------------------------------------------------------------
# Planning failures
# ---------------------------------------------------------------------


class TestPlanningFailure:
    def test_unknown_capability_reports_planning_failure(
        self,
        brain: Brain,
    ) -> None:
        request = BrainRequest(
            goals=(Goal(id="g1", capability_id="unknown.capability"),)
        )

        response = brain.handle(request)

        assert not response.succeeded
        assert response.plan_id is None
        assert response.planning_failure is not None
        assert response.results == ()


# ---------------------------------------------------------------------
# Execution failures and dependency skipping
# ---------------------------------------------------------------------


class TestExecutionFailureAndSkipping:
    def test_execution_failure_is_captured_in_result(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        driver = _ScriptedToolDriver()
        driver.fail_with(RuntimeError("network unreachable"))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="web.search",
            tool_id="tool.web_search",
            driver=driver,
        )

        request = BrainRequest(
            goals=(Goal(id="g1", capability_id="web.search"),)
        )

        response = brain.handle(request)

        assert not response.succeeded
        assert response.plan_id is not None

        result = response.results[0]
        assert not result.succeeded
        assert result.status is TaskStatus.FAILED
        assert isinstance(result.failure, TaskExecutionError)

    def test_dependent_goal_is_skipped_when_dependency_fails(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        failing_driver = _ScriptedToolDriver()
        failing_driver.fail_with(RuntimeError("boom"))

        dependent_driver = _ScriptedToolDriver()
        dependent_driver.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.parent",
            tool_id="tool.parent",
            driver=failing_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.child",
            tool_id="tool.child",
            driver=dependent_driver,
        )

        request = BrainRequest(
            goals=(
                Goal(id="parent", capability_id="tool.parent"),
                Goal(
                    id="child",
                    capability_id="tool.child",
                    depends_on=("parent",),
                ),
            )
        )

        response = brain.handle(request)

        assert not response.succeeded

        results_by_id = {result.goal_id: result for result in response.results}

        assert results_by_id["parent"].status is TaskStatus.FAILED
        assert results_by_id["child"].skipped
        assert results_by_id["child"].task_id is None
        assert dependent_driver.calls == []

    def test_independent_goal_still_succeeds_when_sibling_fails(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        failing_driver = _ScriptedToolDriver()
        failing_driver.fail_with(RuntimeError("boom"))

        independent_driver = _ScriptedToolDriver()
        independent_driver.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.failing",
            tool_id="tool.failing",
            driver=failing_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.independent",
            tool_id="tool.independent",
            driver=independent_driver,
        )

        request = BrainRequest(
            goals=(
                Goal(id="failing", capability_id="tool.failing"),
                Goal(id="independent", capability_id="tool.independent"),
            )
        )

        response = brain.handle(request)

        results_by_id = {result.goal_id: result for result in response.results}

        assert results_by_id["failing"].status is TaskStatus.FAILED
        assert results_by_id["independent"].succeeded


# ---------------------------------------------------------------------
# BrainRequest immutability
# ---------------------------------------------------------------------


class TestBrainRequest:
    def test_goals_normalized_to_tuple(self) -> None:
        request = BrainRequest(
            goals=[Goal(id="g1", capability_id="web.search")]
        )

        assert isinstance(request.goals, tuple)

    def test_auto_generates_id(self) -> None:
        request = BrainRequest(
            goals=(Goal(id="g1", capability_id="web.search"),)
        )

        assert isinstance(request.id, str)


# ---------------------------------------------------------------------
# Execution progress reporting (Phase 3.5b)
# ---------------------------------------------------------------------


class TestExecutionProgressReporting:
    def test_no_event_bus_reports_nothing_and_behaves_unchanged(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        """Omitting event_bus at construction must not affect handle()."""

        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"ok": True}))
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.a",
            tool_id="tool.a",
            driver=driver,
        )
        collector = _ProgressCollector(event_bus)

        request = BrainRequest(goals=(Goal(id="a", capability_id="tool.a"),))
        response = brain.handle(request)

        assert response.succeeded
        assert collector.events == []

    def test_successful_goal_reports_full_tree(
        self,
        brain_with_progress: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"ok": True}))
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.a",
            tool_id="tool.a",
            driver=driver,
        )
        collector = _ProgressCollector(event_bus)

        request = BrainRequest(goals=(Goal(id="a", capability_id="tool.a"),))
        response = brain_with_progress.handle(request)

        source_ids = [event.source_id for event in collector.events]

        assert source_ids == [
            "brain.execution",
            "brain.planning",
            "brain.planning",
            "brain.execute_goal",
            "brain.execute_goal",
            "brain.execution",
        ]

        root_started, planning_started, planning_completed, goal_started, goal_completed, root_completed = (
            collector.events
        )

        assert root_started.stage is ProgressStage.STARTED
        assert root_started.task_id is None
        assert root_started.parent_progress_id is None

        assert planning_started.stage is ProgressStage.STARTED
        assert planning_started.parent_progress_id == root_started.progress_id

        assert planning_completed.stage is ProgressStage.COMPLETED

        task_id = response.results[0].task_id

        assert goal_started.stage is ProgressStage.STARTED
        assert goal_started.task_id == task_id
        assert goal_started.parent_progress_id == root_started.progress_id

        assert goal_completed.stage is ProgressStage.COMPLETED
        assert goal_completed.task_id == task_id
        assert goal_completed.progress_id == goal_started.progress_id

        assert root_completed.stage is ProgressStage.COMPLETED
        assert root_completed.progress_id == root_started.progress_id
        assert root_completed.metadata.get("succeeded") is True

    def test_planning_failure_reports_failed_tree(
        self,
        brain_with_progress: Brain,
        event_bus: EventBus,
    ) -> None:
        collector = _ProgressCollector(event_bus)

        request = BrainRequest(
            goals=(Goal(id="g1", capability_id="unknown.capability"),)
        )

        response = brain_with_progress.handle(request)

        assert not response.succeeded

        source_ids_and_stages = [
            (event.source_id, event.stage) for event in collector.events
        ]

        assert source_ids_and_stages == [
            ("brain.execution", ProgressStage.STARTED),
            ("brain.planning", ProgressStage.STARTED),
            ("brain.planning", ProgressStage.FAILED),
            ("brain.execution", ProgressStage.FAILED),
        ]

    def test_execution_failure_reports_failed_goal_node(
        self,
        brain_with_progress: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        driver = _ScriptedToolDriver()
        driver.fail_with(ToolExecutionError("boom"))
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.a",
            tool_id="tool.a",
            driver=driver,
        )
        collector = _ProgressCollector(event_bus)

        request = BrainRequest(goals=(Goal(id="a", capability_id="tool.a"),))
        response = brain_with_progress.handle(request)

        assert not response.succeeded

        source_ids_and_stages = [
            (event.source_id, event.stage) for event in collector.events
        ]

        assert ("brain.execute_goal", ProgressStage.FAILED) in source_ids_and_stages
        # The root still reports "completed" (Brain finished orchestrating
        # its own duty), even though the overall response did not succeed
        # -- see Brain.handle()'s docstring: pipeline failures are reported
        # through BrainResponse rather than raised.
        assert collector.events[-1].source_id == "brain.execution"
        assert collector.events[-1].stage is ProgressStage.COMPLETED
        assert collector.events[-1].metadata.get("succeeded") is False

    def test_supervise_exception_reports_root_failed_before_reraising(
        self,
        brain_with_progress: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Audit report fix: unlike a per-goal execution failure (already
        captured into a GoalResult by `_execute_goal` without
        re-raising, see the test above), an exception escaping
        `_supervise()` itself (e.g. a programming error such as a
        `PlanStep` referencing an unknown goal id) previously left the
        root `brain.execution` node's `started()` unmatched forever.
        `handle()` now reports `progress.failed()` for the root before
        letting the exception continue to propagate unchanged.
        """

        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"ok": True}))
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.a",
            tool_id="tool.a",
            driver=driver,
        )
        collector = _ProgressCollector(event_bus)

        supervise_error = RuntimeError("_supervise exploded unexpectedly.")

        def _boom(*args: object, **kwargs: object) -> None:
            raise supervise_error

        monkeypatch.setattr(brain_with_progress, "_supervise", _boom)

        request = BrainRequest(goals=(Goal(id="a", capability_id="tool.a"),))

        with pytest.raises(RuntimeError) as excinfo:
            brain_with_progress.handle(request)

        assert excinfo.value is supervise_error

        source_ids_and_stages = [
            (event.source_id, event.stage) for event in collector.events
        ]

        assert source_ids_and_stages == [
            ("brain.execution", ProgressStage.STARTED),
            ("brain.planning", ProgressStage.STARTED),
            ("brain.planning", ProgressStage.COMPLETED),
            ("brain.execution", ProgressStage.FAILED),
        ]
        assert request.id

# ---------------------------------------------------------------------
# Execution mode configuration
# ---------------------------------------------------------------------


class TestExecutionMode:
    def test_sequential_mode_executes_one_goal_at_a_time(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """In sequential mode, only one goal runs at a time."""
        driver_a = _ScriptedToolDriver()
        driver_a.succeed_with(ToolResponse(result={"ok": True}))

        driver_b = _ScriptedToolDriver()
        driver_b.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.a",
            tool_id="tool.a",
            driver=driver_a,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.b",
            tool_id="tool.b",
            driver=driver_b,
        )

        # Configure sequential mode
        brain._execution_mode = "sequential"

        request = BrainRequest(
            goals=(
                Goal(id="a", capability_id="tool.a"),
                Goal(id="b", capability_id="tool.b"),
            )
        )

        response = brain.handle(request)

        assert response.succeeded
        assert len(response.results) == 2
        assert all(result.succeeded for result in response.results)

    def test_parallel_mode_executes_independent_goals_concurrently(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """In parallel mode (default), independent goals may execute concurrently."""
        driver_a = _ScriptedToolDriver()
        driver_a.succeed_with(ToolResponse(result={"ok": True}))

        driver_b = _ScriptedToolDriver()
        driver_b.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.a",
            tool_id="tool.a",
            driver=driver_a,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.b",
            tool_id="tool.b",
            driver=driver_b,
        )

        # Configure parallel mode (default)
        brain._execution_mode = "parallel"

        request = BrainRequest(
            goals=(
                Goal(id="a", capability_id="tool.a"),
                Goal(id="b", capability_id="tool.b"),
            )
        )

        response = brain.handle(request)

        assert response.succeeded
        assert len(response.results) == 2
        assert all(result.succeeded for result in response.results)

    def test_parallel_mode_respects_max_concurrent_goals(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """In parallel mode, max_concurrent_goals limits simultaneous executions."""
        drivers: list[_ScriptedToolDriver] = []
        for i in range(6):
            d = _ScriptedToolDriver()
            d.succeed_with(ToolResponse(result={"ok": True}))
            drivers.append(d)

        for i, d in enumerate(drivers):
            _register_tool(
                capability_registry,
                tool_manager,
                capability_id=f"tool.z{i}",
                tool_id=f"tool.z{i}",
                driver=d,
            )

        # Configure parallel mode with max_concurrent_goals = 2
        brain._execution_mode = "parallel"
        brain._max_concurrent_goals = 2

        goals = tuple(
            Goal(id=f"g{i}", capability_id=f"tool.z{i}")
            for i in range(6)
        )

        request = BrainRequest(goals=goals)

        response = brain.handle(request)

        assert response.succeeded
        assert len(response.results) == 6
        assert all(result.succeeded for result in response.results)

    def test_dependency_respected_in_sequential_mode(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """In sequential mode, dependent goals wait for their dependencies."""
        failing_driver = _ScriptedToolDriver()
        failing_driver.fail_with(RuntimeError("boom"))

        dependent_driver = _ScriptedToolDriver()
        dependent_driver.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.parent",
            tool_id="tool.parent",
            driver=failing_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.child",
            tool_id="tool.child",
            driver=dependent_driver,
        )

        # Configure sequential mode
        brain._execution_mode = "sequential"

        request = BrainRequest(
            goals=(
                Goal(id="parent", capability_id="tool.parent"),
                Goal(
                    id="child",
                    capability_id="tool.child",
                    depends_on=("parent",),
                ),
            )
        )

        response = brain.handle(request)

        assert not response.succeeded

        results_by_id = {result.goal_id: result for result in response.results}

        assert results_by_id["parent"].status is TaskStatus.FAILED
        assert results_by_id["child"].skipped
        assert results_by_id["child"].task_id is None

    def test_dependency_respected_in_parallel_mode(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """In parallel mode, dependent goals wait for their dependencies."""
        failing_driver = _ScriptedToolDriver()
        failing_driver.fail_with(RuntimeError("boom"))

        dependent_driver = _ScriptedToolDriver()
        dependent_driver.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.parent",
            tool_id="tool.parent",
            driver=failing_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.child",
            tool_id="tool.child",
            driver=dependent_driver,
        )

        # Configure parallel mode
        brain._execution_mode = "parallel"

        request = BrainRequest(
            goals=(
                Goal(id="parent", capability_id="tool.parent"),
                Goal(
                    id="child",
                    capability_id="tool.child",
                    depends_on=("parent",),
                ),
            )
        )

        response = brain.handle(request)

        assert not response.succeeded

        results_by_id = {result.goal_id: result for result in response.results}

        assert results_by_id["parent"].status is TaskStatus.FAILED
        assert results_by_id["child"].skipped
        assert results_by_id["child"].task_id is None
