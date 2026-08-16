"""
Unit tests for ToolManager.

These tests use the real `Logger`/`EventBus` fixtures from
`tests/conftest.py`, since `ToolManager.__init__` performs a strict
`type(event_bus) is not EventBus` / `type(logger) is not Logger`
check and rejects fakes/mocks.

BUG FOUND (documented, not fixed -- see final report):
    `ToolManager.execute()` (parika/core/tool_manager/tool_manager.py,
    the `if type(response) is not ToolResponse: raise
    ToolExecutionError(...)` check around lines 411-414) raises its
    "invalid response" error *inside* the same `try` block guarded by
    the generic `except Exception as ex:` clause a few lines below
    (line 416). As a result, that raise is caught by its own sibling
    except-clause and gets wrapped a second time: the final error
    message reads "Execution of tool '<id>' failed: Tool '<id>'
    returned an invalid response." instead of surfacing the clean,
    single message, and the raised error's `__cause__` is the *inner*
    `ToolExecutionError` rather than `None` or the driver's return
    value. `TestExecute.test_driver_returning_wrong_response_type_is_double_wrapped`
    below pins down this current (odd but non-crashing) behavior.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.tool_manager.events import (
    ToolExecuted,
    ToolExecutionFailed,
    ToolRegistered,
    ToolUnregistered,
)
from parika.core.tool_manager.exceptions import (
    InvalidToolError,
    ToolAlreadyRegisteredError,
    ToolExecutionError,
    ToolNotFoundError,
)
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


class _RecordingDriver:
    """
    Minimal ToolDriver-compatible test double.

    `ToolDriver` is a `runtime_checkable` Protocol, so this class
    intentionally does not inherit from any base class -- it only
    needs to structurally provide a matching `execute` method.
    """

    def __init__(
        self,
        *,
        response: ToolResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[ToolRequest] = []
        self._response = response
        self._error = error

    def execute(self, request: ToolRequest) -> ToolResponse:
        self.calls.append(request)

        if self._error is not None:
            raise self._error

        assert self._response is not None
        return self._response


def _make_tool(**overrides: Any) -> Tool:
    """Build a valid Tool, overriding only the fields under test."""

    fields: dict[str, Any] = {
        "id": "tool.example",
        "name": "Example Tool",
        "version": "1.0.0",
        "description": "An example tool used in tests.",
    }
    fields.update(overrides)
    return Tool(**fields)


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


# ---------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------


class TestTool:
    def test_constructs_with_defaults(self) -> None:
        tool = _make_tool()

        assert tool.id == "tool.example"
        assert tool.enabled is True
        assert tool.capabilities == ()
        assert dict(tool.metadata) == {}

    def test_normalizes_capabilities_to_immutable_tuple(self) -> None:
        tool = _make_tool(capabilities=["a", "b"])

        assert tool.capabilities == ("a", "b")

    def test_metadata_is_immutable(self) -> None:
        tool = _make_tool(metadata={"key": "value"})

        with pytest.raises(TypeError):
            tool.metadata["key"] = "other"  # type: ignore[index]

    def test_input_metadata_mutation_does_not_affect_tool(self) -> None:
        source = {"key": "value"}
        tool = _make_tool(metadata=source)

        source["key"] = "changed"

        assert tool.metadata["key"] == "value"

    def test_rejects_empty_id(self) -> None:
        with pytest.raises(InvalidToolError):
            _make_tool(id="   ")

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(InvalidToolError):
            _make_tool(name="")

    def test_rejects_empty_version(self) -> None:
        with pytest.raises(InvalidToolError):
            _make_tool(version="")

    def test_rejects_empty_description(self) -> None:
        with pytest.raises(InvalidToolError):
            _make_tool(description="")

    def test_rejects_empty_capability_identifier(self) -> None:
        with pytest.raises(InvalidToolError):
            _make_tool(capabilities=("valid", ""))

    def test_rejects_duplicate_capability_identifiers(self) -> None:
        with pytest.raises(InvalidToolError):
            _make_tool(capabilities=("duplicate", "duplicate"))


# ---------------------------------------------------------------------
# ToolRequest
# ---------------------------------------------------------------------


class TestToolRequest:
    def test_defaults_to_empty_immutable_mappings(self) -> None:
        request = ToolRequest()

        assert dict(request.arguments) == {}
        assert dict(request.parameters) == {}
        assert dict(request.metadata) == {}

    def test_mappings_are_immutable(self) -> None:
        request = ToolRequest(
            arguments={"query": "parika"},
            parameters={"timeout": 5},
            metadata={"caller": "test"},
        )

        with pytest.raises(TypeError):
            request.arguments["query"] = "other"  # type: ignore[index]

        with pytest.raises(TypeError):
            request.parameters["timeout"] = 10  # type: ignore[index]

        with pytest.raises(TypeError):
            request.metadata["caller"] = "other"  # type: ignore[index]

    def test_input_mapping_mutation_does_not_affect_request(self) -> None:
        source = {"query": "parika"}
        request = ToolRequest(arguments=source)

        source["query"] = "changed"

        assert request.arguments["query"] == "parika"


# ---------------------------------------------------------------------
# ToolResponse
# ---------------------------------------------------------------------


class TestToolResponse:
    def test_defaults(self) -> None:
        response = ToolResponse()

        assert response.result is None
        assert dict(response.attributes) == {}

    def test_attributes_are_immutable(self) -> None:
        response = ToolResponse(attributes={"count": 1})

        with pytest.raises(TypeError):
            response.attributes["count"] = 2  # type: ignore[index]

    def test_input_mapping_mutation_does_not_affect_response(self) -> None:
        source = {"count": 1}
        response = ToolResponse(attributes=source)

        source["count"] = 2

        assert response.attributes["count"] == 1


# ---------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------


class TestRegister:
    def test_registers_tool_and_driver(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("tool.registered", subscriber)

        tool = _make_tool()
        driver = _RecordingDriver(response=ToolResponse())

        tool_manager.register(tool, driver)

        assert tool_manager.contains(tool.id)
        assert tool_manager.get(tool.id) is tool
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ToolRegistered)
        assert event.tool_id == tool.id

    def test_rejects_duplicate_registration(
        self,
        tool_manager: ToolManager,
    ) -> None:
        tool = _make_tool()
        driver = _RecordingDriver(response=ToolResponse())
        tool_manager.register(tool, driver)

        with pytest.raises(ToolAlreadyRegisteredError):
            tool_manager.register(tool, driver)

    def test_rejects_non_tool_instance(
        self,
        tool_manager: ToolManager,
    ) -> None:
        driver = _RecordingDriver(response=ToolResponse())

        with pytest.raises(InvalidToolError):
            tool_manager.register(
                "not-a-tool",  # type: ignore[arg-type]
                driver,
            )

    def test_rejects_invalid_driver(
        self,
        tool_manager: ToolManager,
    ) -> None:
        tool = _make_tool()

        with pytest.raises(InvalidToolError):
            tool_manager.register(
                tool,
                object(),  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------
# unregister()
# ---------------------------------------------------------------------


class TestUnregister:
    def test_unregisters_tool_and_driver(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("tool.unregistered", subscriber)

        tool = _make_tool()
        driver = _RecordingDriver(response=ToolResponse())
        tool_manager.register(tool, driver)

        tool_manager.unregister(tool.id)

        assert not tool_manager.contains(tool.id)
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ToolUnregistered)
        assert event.tool_id == tool.id

    def test_raises_when_missing(
        self,
        tool_manager: ToolManager,
    ) -> None:
        with pytest.raises(ToolNotFoundError):
            tool_manager.unregister("missing")

    def test_unregistered_tool_can_no_longer_be_executed(
        self,
        tool_manager: ToolManager,
    ) -> None:
        tool = _make_tool()
        driver = _RecordingDriver(response=ToolResponse())
        tool_manager.register(tool, driver)
        tool_manager.unregister(tool.id)

        with pytest.raises(ToolNotFoundError):
            tool_manager.execute(tool.id, ToolRequest())


# ---------------------------------------------------------------------
# get() / contains() / get_all() / count()
# ---------------------------------------------------------------------


class TestRegistryAccessors:
    def test_get_raises_when_missing(
        self,
        tool_manager: ToolManager,
    ) -> None:
        with pytest.raises(ToolNotFoundError):
            tool_manager.get("missing")

    def test_contains_reflects_registration_state(
        self,
        tool_manager: ToolManager,
    ) -> None:
        assert tool_manager.contains("tool.example") is False

        tool_manager.register(
            _make_tool(),
            _RecordingDriver(response=ToolResponse()),
        )

        assert tool_manager.contains("tool.example") is True

    def test_get_all_empty_when_nothing_registered(
        self,
        tool_manager: ToolManager,
    ) -> None:
        assert tool_manager.get_all() == ()
        assert tool_manager.count() == 0

    def test_get_all_and_count(
        self,
        tool_manager: ToolManager,
    ) -> None:
        tool_a = _make_tool(id="tool.a")
        tool_b = _make_tool(id="tool.b")
        tool_manager.register(
            tool_a, _RecordingDriver(response=ToolResponse())
        )
        tool_manager.register(
            tool_b, _RecordingDriver(response=ToolResponse())
        )

        result = tool_manager.get_all()

        # Note: Tool is not put into a `set` here -- its `metadata`
        # field is a MappingProxyType, which is unhashable, so a
        # frozen-dataclass-generated `__hash__` on Tool would raise.
        assert tool_manager.count() == 2
        assert {t.id for t in result} == {"tool.a", "tool.b"}
        assert tool_a in result
        assert tool_b in result


# ---------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------


class TestExecute:
    def test_execute_returns_response_and_publishes_event(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("tool.executed", subscriber)

        tool = _make_tool()
        response = ToolResponse(result="ok", attributes={"count": 1})
        driver = _RecordingDriver(response=response)
        tool_manager.register(tool, driver)

        request = ToolRequest(arguments={"query": "parika"})
        result = tool_manager.execute(tool.id, request)

        assert result is response
        assert driver.calls == [request]
        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, ToolExecuted)
        assert event.tool_id == tool.id
        assert event.request is request
        assert event.response is response

    def test_raises_when_tool_not_registered(
        self,
        tool_manager: ToolManager,
    ) -> None:
        with pytest.raises(ToolNotFoundError):
            tool_manager.execute("missing", ToolRequest())

    def test_raises_when_request_type_invalid(
        self,
        tool_manager: ToolManager,
    ) -> None:
        tool = _make_tool()
        driver = _RecordingDriver(response=ToolResponse())
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError) as excinfo:
            tool_manager.execute(
                tool.id,
                {"not": "a request"},  # type: ignore[arg-type]
            )

        # Request-type validation happens before any driver
        # interaction or event publication, and raises directly
        # (no chained cause, no driver call).
        assert excinfo.value.__cause__ is None
        assert driver.calls == []

    def test_request_type_validated_even_for_unknown_tool(
        self,
        tool_manager: ToolManager,
    ) -> None:
        # `_validate_request()` runs before the tool/driver lookup,
        # so an invalid request type is rejected as a request-type
        # error even when `tool_id` is not registered at all.
        with pytest.raises(ToolExecutionError):
            tool_manager.execute(
                "missing",
                "not-a-request",  # type: ignore[arg-type]
            )

    def test_driver_exception_is_wrapped_and_published(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("tool.execution_failed", failed)

        tool = _make_tool()
        original_error = RuntimeError("boom")
        driver = _RecordingDriver(error=original_error)
        tool_manager.register(tool, driver)

        request = ToolRequest()
        with pytest.raises(ToolExecutionError) as excinfo:
            tool_manager.execute(tool.id, request)

        assert excinfo.value.__cause__ is original_error
        assert len(failed.received) == 1
        event = failed.received[0]
        assert isinstance(event, ToolExecutionFailed)
        assert event.tool_id == tool.id
        assert event.request is request
        assert event.exception is excinfo.value

    def test_driver_returning_wrong_response_type_is_double_wrapped(
        self,
        tool_manager: ToolManager,
        event_bus: EventBus,
    ) -> None:
        """
        Pins down the "BUG FOUND" behavior documented in the module
        docstring: the invalid-response-type check inside
        `ToolManager.execute()` raises `ToolExecutionError` from
        within the very `try` block whose `except Exception` clause
        re-wraps it, producing a doubly-wrapped message and an
        `__cause__` that is itself a `ToolExecutionError`.
        """

        failed = RecordingSubscriber()
        event_bus.subscribe("tool.execution_failed", failed)

        tool = _make_tool()
        driver = _RecordingDriver(
            response="not-a-response",  # type: ignore[arg-type]
        )
        tool_manager.register(tool, driver)

        with pytest.raises(ToolExecutionError) as excinfo:
            tool_manager.execute(tool.id, ToolRequest())

        message = str(excinfo.value)
        assert f"Execution of tool '{tool.id}' failed:" in message
        assert "returned an invalid response" in message

        inner = excinfo.value.__cause__
        assert isinstance(inner, ToolExecutionError)
        assert "returned an invalid response" in str(inner)

        assert len(failed.received) == 1
        failed_event = failed.received[0]
        assert isinstance(failed_event, ToolExecutionFailed)
        assert failed_event.exception is excinfo.value


# ---------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_registration_of_distinct_tools_succeeds(
        self,
        tool_manager: ToolManager,
    ) -> None:
        tools = [_make_tool(id=f"tool.{i}") for i in range(50)]
        errors: list[Exception] = []

        def _register(tool: Tool) -> None:
            try:
                tool_manager.register(
                    tool,
                    _RecordingDriver(response=ToolResponse()),
                )
            except Exception as ex:  # pragma: no cover - failure path
                errors.append(ex)

        threads = [
            threading.Thread(target=_register, args=(tool,))
            for tool in tools
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert errors == []
        assert tool_manager.count() == 50
        assert all(tool_manager.contains(tool.id) for tool in tools)
