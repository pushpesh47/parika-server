"""
Unit tests for CapabilityExecutor.

CapabilityExecutor is exercised against real ToolManager and
ProviderManager instances (both strictly type-check their Logger and
EventBus dependencies, so real Logger/EventBus instances are used via
the shared `logger`/`event_bus` fixtures). A minimal fake ToolDriver
and ProviderDriver drive the TOOL and PROVIDER execution paths without
depending on TaskManager or Planner, which sit above CapabilityExecutor
in the stack.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from parika.core.capability_executor.capability_executor import (
    CapabilityExecutor,
)
from parika.core.capability_executor.events import (
    CapabilityExecutionCompletedEvent,
    CapabilityExecutionFailedEvent,
    CapabilityExecutionStartedEvent,
)
from parika.core.capability_executor.exceptions import (
    CapabilityExecutionError,
    InvalidCapabilityExecutionRequestError,
    InvalidExecutionTargetError,
)
from parika.core.capability_executor.execution_backend import (
    ExecutionBackend,
)
from parika.core.capability_executor.execution_target import (
    ExecutionTarget,
)
from parika.core.capability_executor.request import (
    CapabilityExecutionRequest,
)
from parika.core.capability_executor.response import (
    CapabilityExecutionResponse,
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
from parika.core.capability_resolver.capability_request import (
    CapabilityRequest,
)
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager


class RecordingSubscriber:
    """EventBus subscriber that records every payload it receives."""

    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


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


class _ScriptedProviderDriver(ProviderDriver):
    """Provider driver returning scripted responses/exceptions per call."""

    def __init__(self) -> None:
        self.calls: list[tuple[ProviderModel, ProviderRequest]] = []
        self._response: ProviderResponse | None = None
        self._error: Exception | None = None

    def succeed_with(self, response: ProviderResponse) -> None:
        self._response = response
        self._error = None

    def fail_with(self, error: Exception) -> None:
        self._error = error
        self._response = None

    def discover_models(self) -> frozenset[ProviderModel]:
        return frozenset()

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    def execute(
        self,
        model: ProviderModel,
        request: ProviderRequest,
    ) -> ProviderResponse:
        self.calls.append((model, request))

        if self._error is not None:
            raise self._error

        assert self._response is not None
        return self._response


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def provider_manager(event_bus: EventBus, logger: Logger) -> ProviderManager:
    return ProviderManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def capability_registry(
    event_bus: EventBus,
    logger: Logger,
) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


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


def _make_resolution(
    *,
    capability_id: str = "web.search",
    category: CapabilityCategory = CapabilityCategory.TOOL,
) -> CapabilityResolution:
    return CapabilityResolution(
        request=CapabilityRequest(capability_id=capability_id),
        definition=CapabilityDefinition(
            id=capability_id,
            name=capability_id,
            description=capability_id,
            category=category,
        ),
        resolved_at=datetime.now(UTC),
    )


def _register_tool(
    tool_manager: ToolManager,
    driver: _ScriptedToolDriver,
    *,
    tool_id: str = "tool.web_search",
    capability_id: str = "web.search",
) -> None:
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


def _register_provider(
    provider_manager: ProviderManager,
    driver: _ScriptedProviderDriver,
    model: ProviderModel,
    *,
    provider_id: str = "provider.ollama",
) -> None:
    provider_manager.register(
        Provider(
            id=provider_id,
            name=provider_id,
            models=(model,),  # type: ignore[arg-type]
        ),
        driver,
    )


def _make_tool_execution_request(
    *,
    tool_id: str = "tool.web_search",
    capability_id: str = "web.search",
    arguments: dict[str, Any] | None = None,
) -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        resolution=_make_resolution(
            capability_id=capability_id,
            category=CapabilityCategory.TOOL,
        ),
        target=ExecutionTarget(
            backend=ExecutionBackend.TOOL,
            identifier=tool_id,
        ),
        backend_request=ToolRequest(arguments=arguments or {}),
    )


# ---------------------------------------------------------------------
# execute() - request validation
# ---------------------------------------------------------------------


class TestValidateRequest:
    def test_rejects_non_execution_request(
        self,
        capability_executor: CapabilityExecutor,
    ) -> None:
        with pytest.raises(InvalidCapabilityExecutionRequestError):
            capability_executor.execute(object())  # type: ignore[arg-type]

    def test_invalid_request_does_not_publish_started_event(
        self,
        capability_executor: CapabilityExecutor,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("capability.execution.started", subscriber)

        with pytest.raises(InvalidCapabilityExecutionRequestError):
            capability_executor.execute(object())  # type: ignore[arg-type]

        assert subscriber.received == []


# ---------------------------------------------------------------------
# execute() - TOOL backend success
# ---------------------------------------------------------------------


class TestExecuteToolSuccess:
    def test_delegates_to_tool_manager_and_wraps_response(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
    ) -> None:
        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"results": ["a", "b"]}))
        _register_tool(tool_manager, driver)

        request = _make_tool_execution_request(
            arguments={"query": "parika architecture"},
        )

        response = capability_executor.execute(request)

        assert isinstance(response, CapabilityExecutionResponse)
        assert isinstance(response.backend_response, ToolResponse)
        assert response.backend_response.result == {
            "results": ["a", "b"],
        }
        assert response.duration_seconds is not None
        assert response.duration_seconds >= 0
        assert driver.calls[0].arguments["query"] == "parika architecture"

    def test_publishes_started_and_completed_events(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        started = RecordingSubscriber()
        completed = RecordingSubscriber()
        event_bus.subscribe("capability.execution.started", started)
        event_bus.subscribe("capability.execution.completed", completed)

        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"ok": True}))
        _register_tool(tool_manager, driver)

        capability_executor.execute(_make_tool_execution_request())

        assert len(started.received) == 1
        started_event = started.received[0]
        assert isinstance(started_event, CapabilityExecutionStartedEvent)
        assert started_event.capability_id == "web.search"
        assert started_event.capability_category is CapabilityCategory.TOOL
        assert started_event.backend is ExecutionBackend.TOOL

        assert len(completed.received) == 1
        completed_event = completed.received[0]
        assert isinstance(completed_event, CapabilityExecutionCompletedEvent)
        assert completed_event.capability_id == "web.search"
        assert completed_event.backend is ExecutionBackend.TOOL
        assert completed_event.duration_seconds >= 0

    def test_does_not_publish_failed_event_on_success(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("capability.execution.failed", failed)

        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"ok": True}))
        _register_tool(tool_manager, driver)

        capability_executor.execute(_make_tool_execution_request())

        assert failed.received == []


# ---------------------------------------------------------------------
# execute() - TOOL backend failure
# ---------------------------------------------------------------------


class TestExecuteToolFailure:
    def test_wraps_backend_failure_as_capability_execution_error(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
    ) -> None:
        driver = _ScriptedToolDriver()
        driver.fail_with(RuntimeError("network unreachable"))
        _register_tool(tool_manager, driver)

        with pytest.raises(CapabilityExecutionError) as excinfo:
            capability_executor.execute(_make_tool_execution_request())

        assert excinfo.value.__cause__ is not None

    def test_publishes_failed_event_with_error_details(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("capability.execution.failed", failed)

        driver = _ScriptedToolDriver()
        driver.fail_with(RuntimeError("network unreachable"))
        _register_tool(tool_manager, driver)

        with pytest.raises(CapabilityExecutionError):
            capability_executor.execute(_make_tool_execution_request())

        assert len(failed.received) == 1
        event = failed.received[0]
        assert isinstance(event, CapabilityExecutionFailedEvent)
        assert event.capability_id == "web.search"
        assert event.backend is ExecutionBackend.TOOL
        # ToolManager wraps the original RuntimeError in a
        # ToolExecutionError before it reaches CapabilityExecutor.
        assert event.error_type == "ToolExecutionError"
        assert "network unreachable" in event.error_message

    def test_publishes_started_event_before_failing(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        started = RecordingSubscriber()
        event_bus.subscribe("capability.execution.started", started)

        driver = _ScriptedToolDriver()
        driver.fail_with(RuntimeError("boom"))
        _register_tool(tool_manager, driver)

        with pytest.raises(CapabilityExecutionError):
            capability_executor.execute(_make_tool_execution_request())

        assert len(started.received) == 1

    def test_raises_when_tool_is_not_registered(
        self,
        capability_executor: CapabilityExecutor,
    ) -> None:
        request = _make_tool_execution_request(tool_id="tool.missing")

        with pytest.raises(CapabilityExecutionError):
            capability_executor.execute(request)


# ---------------------------------------------------------------------
# execute() - task_id correlation (Phase 3.5b)
# ---------------------------------------------------------------------


class TestExecuteTaskIdCorrelation:
    def test_forwards_task_id_onto_started_and_completed_events(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        started = RecordingSubscriber()
        completed = RecordingSubscriber()
        event_bus.subscribe("capability.execution.started", started)
        event_bus.subscribe("capability.execution.completed", completed)

        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"ok": True}))
        _register_tool(tool_manager, driver)

        capability_executor.execute(
            _make_tool_execution_request(), task_id="task-123"
        )

        assert started.received[0].task_id == "task-123"
        assert completed.received[0].task_id == "task-123"

    def test_forwards_task_id_onto_failed_event(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("capability.execution.failed", failed)

        driver = _ScriptedToolDriver()
        driver.fail_with(RuntimeError("boom"))
        _register_tool(tool_manager, driver)

        with pytest.raises(CapabilityExecutionError):
            capability_executor.execute(
                _make_tool_execution_request(), task_id="task-456"
            )

        assert failed.received[0].task_id == "task-456"

    def test_defaults_to_none_when_omitted(
        self,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        started = RecordingSubscriber()
        event_bus.subscribe("capability.execution.started", started)

        driver = _ScriptedToolDriver()
        driver.succeed_with(ToolResponse(result={"ok": True}))
        _register_tool(tool_manager, driver)

        capability_executor.execute(_make_tool_execution_request())

        assert started.received[0].task_id is None


# ---------------------------------------------------------------------
# execute() - PROVIDER backend
# ---------------------------------------------------------------------


class TestExecuteProvider:
    def test_delegates_to_provider_manager_and_wraps_response(
        self,
        capability_executor: CapabilityExecutor,
        provider_manager: ProviderManager,
    ) -> None:
        model = ProviderModel(
            id="llama3",
            name="Llama 3",
            capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        )
        driver = _ScriptedProviderDriver()
        response_sentinel = ProviderResponse(model_id="llama3")
        driver.succeed_with(response_sentinel)
        _register_provider(provider_manager, driver, model)

        provider_request = ProviderRequest()
        execution_request = CapabilityExecutionRequest(
            resolution=_make_resolution(
                capability_id="chat.generate",
                category=CapabilityCategory.LLM,
            ),
            target=ExecutionTarget(
                backend=ExecutionBackend.PROVIDER,
                identifier="provider.ollama",
                model=model,
            ),
            backend_request=provider_request,
        )

        response = capability_executor.execute(execution_request)

        assert response.backend_response is response_sentinel
        assert driver.calls == [(model, provider_request)]

    def test_reports_provider_and_model_id_in_metadata(
        self,
        capability_executor: CapabilityExecutor,
        provider_manager: ProviderManager,
    ) -> None:
        """
        Regression test: `metadata["provider_id"]`/`metadata["model_id"]`
        must surface which provider/model actually served the request,
        e.g. for the CLI's `/status` diagnostics and Experience's
        provider_id/model_id fields.
        """

        model = ProviderModel(
            id="llama3",
            name="Llama 3",
            capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        )
        driver = _ScriptedProviderDriver()
        driver.succeed_with(ProviderResponse(model_id="llama3"))
        _register_provider(provider_manager, driver, model)

        execution_request = CapabilityExecutionRequest(
            resolution=_make_resolution(
                capability_id="chat.generate",
                category=CapabilityCategory.LLM,
            ),
            target=ExecutionTarget(
                backend=ExecutionBackend.PROVIDER,
                identifier="provider.ollama",
                model=model,
            ),
            backend_request=ProviderRequest(),
        )

        response = capability_executor.execute(execution_request)

        assert response.metadata["provider_id"] == "provider.ollama"
        assert response.metadata["model_id"] == "llama3"

    def test_publishes_events_with_provider_backend(
        self,
        capability_executor: CapabilityExecutor,
        provider_manager: ProviderManager,
        event_bus: EventBus,
    ) -> None:
        completed = RecordingSubscriber()
        event_bus.subscribe("capability.execution.completed", completed)

        model = ProviderModel(
            id="llama3",
            name="Llama 3",
            capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        )
        driver = _ScriptedProviderDriver()
        driver.succeed_with(ProviderResponse())
        _register_provider(provider_manager, driver, model)

        execution_request = CapabilityExecutionRequest(
            resolution=_make_resolution(
                capability_id="chat.generate",
                category=CapabilityCategory.LLM,
            ),
            target=ExecutionTarget(
                backend=ExecutionBackend.PROVIDER,
                identifier="provider.ollama",
                model=model,
            ),
            backend_request=ProviderRequest(),
        )

        capability_executor.execute(execution_request)

        assert len(completed.received) == 1
        assert completed.received[0].backend is ExecutionBackend.PROVIDER

    def test_wraps_provider_backend_failure(
        self,
        capability_executor: CapabilityExecutor,
        provider_manager: ProviderManager,
    ) -> None:
        model = ProviderModel(
            id="llama3",
            name="Llama 3",
            capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        )
        driver = _ScriptedProviderDriver()
        driver.fail_with(RuntimeError("provider unreachable"))
        _register_provider(provider_manager, driver, model)

        execution_request = CapabilityExecutionRequest(
            resolution=_make_resolution(
                capability_id="chat.generate",
                category=CapabilityCategory.LLM,
            ),
            target=ExecutionTarget(
                backend=ExecutionBackend.PROVIDER,
                identifier="provider.ollama",
                model=model,
            ),
            backend_request=ProviderRequest(),
        )

        with pytest.raises(CapabilityExecutionError) as excinfo:
            capability_executor.execute(execution_request)

        assert isinstance(excinfo.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------
# Request / response immutability
# ---------------------------------------------------------------------


class TestImmutability:
    def test_execution_request_is_frozen(self) -> None:
        request = _make_tool_execution_request()

        with pytest.raises(AttributeError):
            request.backend_request = ToolRequest()  # type: ignore[misc]

    def test_execution_request_metadata_is_defensively_copied(self) -> None:
        mutable_metadata = {"trace_id": "abc"}
        request = CapabilityExecutionRequest(
            resolution=_make_resolution(),
            target=ExecutionTarget(
                backend=ExecutionBackend.TOOL,
                identifier="tool.web_search",
            ),
            backend_request=ToolRequest(),
            metadata=mutable_metadata,
        )

        mutable_metadata["trace_id"] = "mutated"

        # Unlike CapabilityDefinition/CapabilityRequest,
        # CapabilityExecutionRequest correctly defends against mutable
        # metadata via __post_init__.
        assert request.metadata["trace_id"] == "abc"
        with pytest.raises(TypeError):
            request.metadata["new_key"] = "value"  # type: ignore[index]

    def test_execution_response_is_frozen(self) -> None:
        response = CapabilityExecutionResponse(
            backend_response=ToolResponse(),
        )

        with pytest.raises(AttributeError):
            response.duration_seconds = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------
# NOTE: ExecutionTarget previously raised a plain stdlib ValueError for
# invalid backend/model combinations instead of the dedicated
# InvalidExecutionTargetError exception defined for exactly this
# purpose. This was fixed (execution_target.py) to raise
# InvalidExecutionTargetError, matching the project convention of
# never raising stdlib exceptions from Core components.
# ---------------------------------------------------------------------


class TestExecutionTargetValidation:
    def test_tool_backend_rejects_model(self) -> None:
        model = ProviderModel(id="llama3", name="Llama 3")

        with pytest.raises(InvalidExecutionTargetError):
            ExecutionTarget(
                backend=ExecutionBackend.TOOL,
                identifier="tool.web_search",
                model=model,
            )

    def test_provider_backend_requires_model(
        self,
    ) -> None:
        with pytest.raises(InvalidExecutionTargetError):
            ExecutionTarget(
                backend=ExecutionBackend.PROVIDER,
                identifier="provider.ollama",
                model=None,
            )
