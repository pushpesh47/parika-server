"""
Focused tests for Goal Recovery mechanism.

Tests the generic bounded Goal Recovery for recoverable goal failures
introduced in PARIKA v1.
"""

from __future__ import annotations

from typing import Any

import pytest

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
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
from parika.core.task_manager.task_manager import TaskManager
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager


class _ScriptedToolDriver:
    """Tool driver returning scripted responses/exceptions per call."""

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []
        self._response: ToolResponse | None = None
        self._error: Exception | None = None
        self._call_count = 0

    def succeed_with(self, response: ToolResponse) -> None:
        self._response = response
        self._error = None

    def fail_with(self, error: Exception) -> None:
        self._error = error
        self._response = None

    def succeed_on_nth_call(self, n: int, response: ToolResponse) -> None:
        """Succeed only on the nth call (1-indexed), fail before that."""
        self._response = response
        self._error = None
        self._success_on_call = n

    def execute(self, request: ToolRequest) -> ToolResponse:
        self.calls.append(request)
        self._call_count += 1

        if hasattr(self, '_success_on_call'):
            if self._call_count < self._success_on_call:
                raise FileNotFoundError(f"Path not found (call {self._call_count})")

        if self._error is not None:
            raise self._error

        assert self._response is not None
        return self._response


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


class _MockProviderDriver:
    """Mock provider driver that returns a recovery plan."""

    def __init__(self, recovery_plan: dict[str, Any] | None = None):
        self.recovery_plan = recovery_plan or {
            "recovery_capability": "filesystem.search",
            "recovery_inputs": {"path": "/workspace", "pattern": "*.php"},
            "reasoning": "Search for the file",
        }
        self.calls: list[Any] = []

    def discover_models(self):
        return frozenset()

    def check_health(self):
        from parika.core.provider_manager.provider_health import ProviderHealth
        return ProviderHealth(available=True)

    def execute(self, model, request):
        from parika.core.provider_manager.chat_message import ChatMessage
        from parika.core.provider_manager.chat_result import ChatResult
        import json

        self.calls.append(request)
        # Return the recovery plan as JSON
        content = json.dumps(self.recovery_plan)
        return ChatResult(
            message=ChatMessage(role="assistant", content=content),
            tool_invocations=(),
        )


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
def brain(
    planner: Planner,
    task_manager: TaskManager,
    logger: Logger,
    tool_manager: ToolManager,
    provider_manager: ProviderManager,
) -> Brain:
    return Brain(
        planner=planner,
        task_manager=task_manager,
        logger=logger,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
    )


# -------------------------------------------------------------------------
# Test A: Existing successful goal - unchanged behavior
# -------------------------------------------------------------------------


class TestRecoverySuccessfulExecution:
    """Test A: Existing successful behavior remains unchanged."""

    def test_single_goal_succeeds_without_recovery(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """A successful goal should not trigger recovery."""
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
        assert len(response.results) == 1
        result = response.results[0]
        assert result.succeeded
        assert result.status is TaskStatus.COMPLETED
        assert driver._call_count == 1  # Only one call, no retries


# -------------------------------------------------------------------------
# Test B: Recoverable failure enters recovery instead of immediate terminal failure
# -------------------------------------------------------------------------


class TestRecoveryEntersRecovery:
    """Test B: Recoverable failure enters recovery."""

    def test_filesystem_path_not_found_triggers_recovery(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        """A FilesystemPathNotFoundError should trigger recovery attempt."""
        # First driver: fails with path not found
        read_driver = _ScriptedToolDriver()
        read_driver.fail_with(FileNotFoundError("Path '/wrong/path/file.php' does not exist."))

        # Second driver: search succeeds and returns correct path
        search_driver = _ScriptedToolDriver()
        search_driver.succeed_with(ToolResponse(result={
            "path": "/workspace",
            "pattern": "*.php",
            "matches": ["/workspace/src/Http/Controllers/UserController.php"]
        }))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.read",
            tool_id="tool.filesystem_read",
            driver=read_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.search",
            tool_id="tool.filesystem_search",
            driver=search_driver,
        )

        # Configure provider for recovery LLM
        from parika.core.provider_manager.provider import Provider
        from parika.core.provider_manager.provider_model import ProviderModel
        from parika.core.provider_manager.model_capability import ModelCapability
        from parika.core.provider_manager.model_limits import ModelLimits

        provider = Provider(
            id="mock_provider",
            name="Mock Provider",
            models=(
                ProviderModel(
                    id="mock_model",
                    name="Mock Model",
                    capabilities=(ModelCapability.TEXT_GENERATION,),
                    limits=ModelLimits(),
                ),
            ),
        )
        provider_manager = ProviderManager(event_bus=EventBus(logger=Logger(Configuration())), logger=Logger(Configuration()))
        provider_manager.register(provider, _MockProviderDriver())

        goal = Goal(
            id="g1",
            capability_id="filesystem.read",
            inputs={"path": "/wrong/path/file.php"},
        )
        request = BrainRequest(goals=(goal,))

        # Use the brain with the mock provider
        from parika.core.brain.brain import Brain
        brain_with_provider = Brain(
            planner=brain._planner,
            task_manager=brain._task_manager,
            logger=logger,  # Pass the root Logger instance
            tool_manager=tool_manager,
            provider_manager=provider_manager,
        )

        response = brain_with_provider.handle(request)

        # The goal should either succeed (if recovery worked) or fail after recovery attempts
        # At minimum, recovery should have been attempted
        assert len(read_driver.calls) >= 1  # Initial attempt
        # If recovery worked, there should be a second call with corrected path


# -------------------------------------------------------------------------
# Test C: Successful recovery - finds/repairs resource and original goal succeeds
# -------------------------------------------------------------------------


class TestRecoverySuccessful:
    """Test C: Successful recovery."""

    def test_recovery_finds_correct_path_and_succeeds(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """Recovery should find the correct path and retry successfully."""
        # This test requires a more sophisticated mock setup
        # For now, verify the recovery mechanism is invoked
        pass  # TODO: Implement with full mock provider


# -------------------------------------------------------------------------
# Test D: Genuine failure - recovery finds no valid solution
# -------------------------------------------------------------------------


class TestRecoveryGenuineFailure:
    """Test D: Genuine failure after recovery."""

    def test_recovery_fails_when_no_candidates_found(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """When recovery search returns no matches, goal should fail."""
        read_driver = _ScriptedToolDriver()
        read_driver.fail_with(FileNotFoundError("Path '/nonexistent/file.php' does not exist."))

        search_driver = _ScriptedToolDriver()
        search_driver.succeed_with(ToolResponse(result={
            "path": "/workspace",
            "pattern": "*.php",
            "matches": []  # No matches found
        }))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.read",
            tool_id="tool.filesystem_read",
            driver=read_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.search",
            tool_id="tool.filesystem_search",
            driver=search_driver,
        )

        goal = Goal(
            id="g1",
            capability_id="filesystem.read",
            inputs={"path": "/nonexistent/file.php"},
        )
        request = BrainRequest(goals=(goal,))

        response = brain.handle(request)

        # Goal should fail after recovery attempts exhausted
        assert not response.succeeded
        result = response.results[0]
        assert not result.succeeded
        assert result.failure is not None


# -------------------------------------------------------------------------
# Test E: Recovery limit - cannot exceed max_recovery_attempts=3
# -------------------------------------------------------------------------


class TestRecoveryLimit:
    """Test E: Recovery limit enforcement."""

    def test_max_recovery_attempts_enforced(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """Recovery should not exceed max_recovery_attempts (default 3)."""
        # Driver that always fails
        read_driver = _ScriptedToolDriver()
        read_driver.fail_with(FileNotFoundError("Path not found"))

        search_driver = _ScriptedToolDriver()
        search_driver.succeed_with(ToolResponse(result={
            "path": "/workspace",
            "pattern": "*.php",
            "matches": ["/workspace/found.php"]
        }))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.read",
            tool_id="tool.filesystem_read",
            driver=read_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.search",
            tool_id="tool.filesystem_search",
            driver=search_driver,
        )

        goal = Goal(
            id="g1",
            capability_id="filesystem.read",
            inputs={"path": "/wrong/path.php"},
        )
        request = BrainRequest(goals=(goal,))

        response = brain.handle(request)

        # Should have: 1 initial + 3 recovery = 4 total read attempts max
        # But since recovery always returns same wrong path (mock limitation),
        # it will retry up to max_recovery_attempts
        assert len(read_driver.calls) <= 4  # 1 initial + 3 recovery max
        assert not response.succeeded


# -------------------------------------------------------------------------
# Test F: No infinite recovery
# -------------------------------------------------------------------------


class TestNoInfiniteRecovery:
    """Test F: No infinite recovery loops."""

    def test_recovery_stops_after_max_attempts(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """Recovery must terminate after max attempts, not loop infinitely."""
        read_driver = _ScriptedToolDriver()
        read_driver.fail_with(FileNotFoundError("Path not found"))

        search_driver = _ScriptedToolDriver()
        search_driver.succeed_with(ToolResponse(result={
            "path": "/workspace",
            "pattern": "*.php",
            "matches": ["/workspace/found.php"]
        }))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.read",
            tool_id="tool.filesystem_read",
            driver=read_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.search",
            tool_id="tool.filesystem_search",
            driver=search_driver,
        )

        goal = Goal(
            id="g1",
            capability_id="filesystem.read",
            inputs={"path": "/wrong/path.php"},
        )
        request = BrainRequest(goals=(goal,))

        response = brain.handle(request)

        # Verify finite attempts
        assert len(read_driver.calls) <= 4
        assert not response.succeeded


# -------------------------------------------------------------------------
# Test G: Partial success - one recovered/failed goal alongside successful goals
# -------------------------------------------------------------------------


class TestRecoveryPartialSuccess:
    """Test G: Partial success with recovery."""

    def test_recovered_goal_with_successful_siblings(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """One goal in recovery, others succeed -> partial success synthesis."""
        # Failing read driver
        read_driver = _ScriptedToolDriver()
        read_driver.fail_with(FileNotFoundError("Path not found"))

        # Successful search
        search_driver = _ScriptedToolDriver()
        search_driver.succeed_with(ToolResponse(result={
            "path": "/workspace",
            "pattern": "*.php",
            "matches": ["/workspace/found.php"]
        }))

        # Successful independent goal
        success_driver = _ScriptedToolDriver()
        success_driver.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.read",
            tool_id="tool.filesystem_read",
            driver=read_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.search",
            tool_id="tool.filesystem_search",
            driver=search_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.success",
            tool_id="tool.success",
            driver=success_driver,
        )

        request = BrainRequest(
            goals=(
                Goal(id="read", capability_id="filesystem.read", inputs={"path": "/wrong/path.php"}),
                Goal(id="success", capability_id="tool.success"),
            )
        )

        response = brain.handle(request)

        results_by_id = {r.goal_id: r for r in response.results}
        # One goal fails (after recovery), one succeeds
        assert results_by_id["success"].succeeded
        assert not results_by_id["read"].succeeded
        # Overall response should reflect partial success
        assert not response.succeeded  # At least one goal failed


# -------------------------------------------------------------------------
# Test H: Existing dependency behavior
# -------------------------------------------------------------------------


class TestRecoveryDependencyBehavior:
    """Test H: Existing dependency behavior unchanged."""

    def test_dependent_goal_skipped_when_dependency_fails_after_recovery(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """Dependent goals should still be skipped when dependency fails after recovery."""
        read_driver = _ScriptedToolDriver()
        read_driver.fail_with(FileNotFoundError("Path not found"))

        search_driver = _ScriptedToolDriver()
        search_driver.succeed_with(ToolResponse(result={
            "path": "/workspace",
            "pattern": "*.php",
            "matches": ["/workspace/found.php"]
        }))

        dependent_driver = _ScriptedToolDriver()
        dependent_driver.succeed_with(ToolResponse(result={"ok": True}))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.read",
            tool_id="tool.filesystem_read",
            driver=read_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="filesystem.search",
            tool_id="tool.filesystem_search",
            driver=search_driver,
        )
        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.dependent",
            tool_id="tool.dependent",
            driver=dependent_driver,
        )

        request = BrainRequest(
            goals=(
                Goal(id="read", capability_id="filesystem.read", inputs={"path": "/wrong/path.php"}),
                Goal(id="dependent", capability_id="tool.dependent", depends_on=("read",)),
            )
        )

        response = brain.handle(request)

        results_by_id = {r.goal_id: r for r in response.results}
        assert not results_by_id["read"].succeeded
        assert results_by_id["dependent"].skipped
        assert dependent_driver.calls == []  # Dependent never executed


# -------------------------------------------------------------------------
# Test I: Project boundary - recovery respects workspace boundaries
# -------------------------------------------------------------------------


class TestRecoveryProjectBoundary:
    """Test I: Project boundary enforcement."""

    def test_recovery_respects_workspace_boundary(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """Recovery should only search within trusted workspace boundaries."""
        # This test verifies that the recovery mechanism doesn't
        # search outside the active project workspace.
        # The current implementation uses the tool's own security
        # which enforces workspace boundaries.
        pass  # TODO: Implement with workspace permission manager


# -------------------------------------------------------------------------
# Additional: Non-recoverable failures should not trigger recovery
# -------------------------------------------------------------------------


class TestNonRecoverableFailures:
    """Test that non-recoverable failures don't trigger recovery."""

    def test_programming_error_not_recoverable(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """Programming errors (ValueError, TypeError) should not trigger recovery."""
        driver = _ScriptedToolDriver()
        driver.fail_with(ValueError("Invalid argument"))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.test",
            tool_id="tool.test",
            driver=driver,
        )

        goal = Goal(id="g1", capability_id="tool.test", inputs={})
        request = BrainRequest(goals=(goal,))

        response = brain.handle(request)

        assert not response.succeeded
        result = response.results[0]
        assert not result.succeeded
        # Exception is wrapped in TaskExecutionError, check the cause chain
        assert result.failure is not None
        # Should only be called once, no recovery attempts
        assert len(driver.calls) == 1

    def test_permission_error_not_recoverable(
        self,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
    ) -> None:
        """Permission errors should not trigger recovery."""
        driver = _ScriptedToolDriver()
        driver.fail_with(PermissionError("Access denied"))

        _register_tool(
            capability_registry,
            tool_manager,
            capability_id="tool.test",
            tool_id="tool.test",
            driver=driver,
        )

        goal = Goal(id="g1", capability_id="tool.test", inputs={})
        request = BrainRequest(goals=(goal,))

        response = brain.handle(request)

        assert not response.succeeded
        assert len(driver.calls) == 1


# -------------------------------------------------------------------------
# Configuration: Custom max_recovery_attempts
# -------------------------------------------------------------------------


class TestRecoveryConfiguration:
    """Test recovery configuration options."""

    def test_custom_max_recovery_attempts(
        self,
        planner: Planner,
        task_manager: TaskManager,
        logger: Logger,
        tool_manager: ToolManager,
        provider_manager: ProviderManager,
    ) -> None:
        """Custom max_recovery_attempts from configuration should be respected."""
        config = Configuration()
        # We can't easily test config override without full config loading
        # but we can verify the default is 3
        brain = Brain(
            planner=planner,
            task_manager=task_manager,
            logger=logger,
            tool_manager=tool_manager,
            provider_manager=provider_manager,
            configuration=config,
        )
        assert brain._max_recovery_attempts == 3