"""
Framework-driven end-to-end validation of the Provider Tool Calling
lifecycle.

Unlike `test_chat_pipeline.py` (Web Search) and
`test_runtime_info_pipeline.py` (Runtime Info), this suite validates
the *generic* orchestration framework itself:

    Brain -> Planner -> Requirement Inference -> ExecutionRequirements
    -> Model Selection -> Provider -> Native Tool Call ->
    CapabilityExecutor -> ToolManager -> Tool Driver -> Tool Result ->
    Provider -> Final Synthesized Response

Every Tool/Capability used here is a synthetic, generically-named
fixture (`capability.alpha`, `capability.beta`, ...) registered
directly against the real Core stack - never a real, specific
capability (Web Search, Runtime Info, or any future one). This is
intentional: the framework must work identically for any Tool-backed
capability without Provider redesign, and this suite is what proves
that claim, independent of any one capability's own behavior.

Only the outermost Ollama `OllamaTransport` is faked (deterministic,
scripted NDJSON/JSON responses); every PARIKA component in between -
Brain, Planner, Requirement Inference, Model Selection,
CapabilityExecutor, ToolManager, and the real `OllamaProviderDriver` -
is real.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
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
from parika.core.planner.exceptions import NoAvailableProviderModelError
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.exceptions import ToolExecutionError
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.providers.ollama.driver import OllamaProviderDriver
from parika.providers.ollama.manifest import create_ollama_provider
from parika.providers.ollama.messages import OllamaMessage, OllamaToolSpec
from parika.providers.ollama.requests import OllamaChatRequest

CHAT_CAPABILITY_ID = "test.chat"

ALPHA_CAPABILITY_ID = "capability.alpha"
ALPHA_TOOL_ID = "tool.alpha"
ALPHA_TOOL_SPEC = OllamaToolSpec(
    name="tool_alpha",
    description="A synthetic capability used only to validate the framework.",
    capability_id=ALPHA_CAPABILITY_ID,
    parameters={"type": "object", "properties": {"value": {"type": "string"}}},
)

BETA_CAPABILITY_ID = "capability.beta"
BETA_TOOL_ID = "tool.beta"
BETA_TOOL_SPEC = OllamaToolSpec(
    name="tool_beta",
    description="A second synthetic capability used only to validate the framework.",
    capability_id=BETA_CAPABILITY_ID,
    parameters={"type": "object", "properties": {"value": {"type": "string"}}},
)


class _ScriptedToolDriver:
    """Generic ToolDriver returning a scripted response or exception."""

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []
        self._responses: list[ToolResponse | Exception] = []

    def queue_success(self, result: object) -> None:
        self._responses.append(ToolResponse(result=result))

    def queue_failure(self, error: Exception) -> None:
        self._responses.append(error)

    def execute(self, request: ToolRequest) -> ToolResponse:
        self.calls.append(request)
        item = self._responses.pop(0)

        if isinstance(item, Exception):
            raise item

        return item


class _FakeOllamaTransport:
    """Deterministic OllamaTransport standing in for a real Ollama server."""

    def __init__(self) -> None:
        self._chat_queue: list[dict[str, Any] | Exception] = []
        self.chat_payloads: list[dict[str, Any]] = []

    def queue_chat_response(self, response: dict[str, Any]) -> None:
        self._chat_queue.append(response)

    def queue_chat_error(self, error: Exception) -> None:
        self._chat_queue.append(error)

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        if url.endswith("/api/chat"):
            self.chat_payloads.append(dict(payload or {}))
            item = self._chat_queue.pop(0)

            if isinstance(item, Exception):
                raise item

            return item

        return {}

    def stream_lines(
        self, method: str, url: str, *, payload, timeout
    ) -> Iterator[dict[str, Any]]:
        return iter(())


def _assistant_message(
    *, content: str = "", tool_calls: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}

    if tool_calls is not None:
        message["tool_calls"] = tool_calls

    return {"message": message, "done": True}


def _tool_call(name: str, arguments: dict[str, Any], call_id: str = "call_1") -> dict[str, Any]:
    return {
        "id": call_id,
        "function": {"name": name, "arguments": arguments},
    }


class _Pipeline:
    """Bundles the full, real Core stack around a fake Ollama transport."""

    def __init__(self, ollama_transport: _FakeOllamaTransport) -> None:
        configuration = Configuration()
        logger = Logger(configuration)
        event_bus = EventBus(logger=logger)

        self.capability_registry = CapabilityRegistry(
            event_bus=event_bus, logger=logger
        )
        capability_resolver = CapabilityResolver(
            capability_registry=self.capability_registry, logger=logger
        )
        resource_manager = ResourceManager(
            configuration=configuration, logger=logger
        )
        policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
        provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
        self.tool_manager = ToolManager(event_bus=event_bus, logger=logger)

        capability_executor = CapabilityExecutor(
            event_bus=event_bus,
            logger=logger,
            tool_manager=self.tool_manager,
            provider_manager=provider_manager,
        )
        self.task_manager = TaskManager(
            event_bus=event_bus,
            logger=logger,
            capability_executor=capability_executor,
        )
        planner = Planner(
            capability_resolver=capability_resolver,
            resource_manager=resource_manager,
            policy_engine=policy_engine,
            provider_manager=provider_manager,
            tool_manager=self.tool_manager,
            logger=logger,
            configuration=configuration,
        )
        self.brain = Brain(
            planner=planner, task_manager=self.task_manager, logger=logger
        )

        self.capability_registry.register(
            CapabilityDefinition(
                id=CHAT_CAPABILITY_ID,
                name="Test Chat",
                description="Synthetic chat capability for framework tests.",
                category=CapabilityCategory.LLM,
            )
        )

        self.ollama_driver = OllamaProviderDriver(
            transport=ollama_transport,
            logger=logger,
            base_url="http://localhost:11434",
        )
        self.ollama_driver.bind_brain(self.brain)

        provider_manager.register(
            create_ollama_provider(models=(_test_model(),)),
            self.ollama_driver,
        )

    def register_capability(
        self,
        *,
        capability_id: str,
        tool_id: str,
        driver: _ScriptedToolDriver,
    ) -> None:
        self.capability_registry.register(
            CapabilityDefinition(
                id=capability_id,
                name=capability_id,
                description=capability_id,
                category=CapabilityCategory.TOOL,
            )
        )
        self.tool_manager.register(
            Tool(
                id=tool_id,
                name=tool_id,
                version="1.0.0",
                description=tool_id,
                capabilities=(capability_id,),
            ),
            driver,
        )


def _test_model() -> ProviderModel:
    return ProviderModel(
        id="test-model",
        name="test-model",
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        execution_features=frozenset({ModelExecutionFeature.TOOL_CALLING}),
    )


def _provider_request_builder_factory(
    message: str, tools: tuple[OllamaToolSpec, ...]
):
    def _build(resolution, model) -> ProviderRequest:  # noqa: ANN001
        return OllamaChatRequest(
            messages=(OllamaMessage(role="user", content=message),),
            tools=tools,
        )

    return _build


def _chat_goal(
    message: str,
    *,
    tools: tuple[OllamaToolSpec, ...] = (),
    goal_id: str = "chat-1",
) -> Goal:
    return Goal(
        id=goal_id,
        capability_id=CHAT_CAPABILITY_ID,
        inputs={"message": message},
        provider_request_builder=_provider_request_builder_factory(
            message, tools
        ),
    )


@pytest.fixture
def transport() -> _FakeOllamaTransport:
    return _FakeOllamaTransport()


@pytest.fixture
def pipeline(transport: _FakeOllamaTransport) -> _Pipeline:
    return _Pipeline(transport)


# =====================================================================
# 1. Requests requiring NO Tool execution
# =====================================================================


class TestNoToolExecutionRequired:
    def test_direct_response_with_no_tools_advertised(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        transport.queue_chat_response(
            _assistant_message(content="Hello! How can I help?")
        )

        response = pipeline.brain.handle(
            BrainRequest(goals=(_chat_goal("Hello!"),))
        )

        assert response.succeeded
        chat_response = response.results[0].response.outputs["result"]
        assert chat_response.message.content == "Hello! How can I help?"
        assert chat_response.tool_invocations == ()

    def test_no_tool_call_generated_even_when_tools_are_advertised(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        """
        Tools being advertised must never force a tool call: the model
        deciding not to call anything is a fully valid outcome.
        """

        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=_ScriptedToolDriver(),
        )
        transport.queue_chat_response(
            _assistant_message(content="I can answer that directly.")
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(_chat_goal("Hello!", tools=(ALPHA_TOOL_SPEC,)),)
            )
        )

        assert response.succeeded
        chat_response = response.results[0].response.outputs["result"]
        assert chat_response.tool_invocations == ()
        assert transport.chat_payloads[0]["tools"][0]["function"]["name"] == (
            "tool_alpha"
        )


# =====================================================================
# 2. Requests requiring a SINGLE Tool-backed capability
# =====================================================================


class TestSingleToolExecution:
    def test_full_round_trip_through_every_layer(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        tool_driver = _ScriptedToolDriver()
        tool_driver.queue_success({"answer": 42})
        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=tool_driver,
        )

        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[_tool_call("tool_alpha", {"value": "x"})]
            )
        )
        transport.queue_chat_response(
            _assistant_message(content="The answer is 42.")
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    _chat_goal("What is the answer?", tools=(ALPHA_TOOL_SPEC,)),
                ),
            )
        )

        assert response.succeeded
        chat_response = response.results[0].response.outputs["result"]
        assert chat_response.message.content == "The answer is 42."

        assert len(chat_response.tool_invocations) == 1
        invocation = chat_response.tool_invocations[0]
        assert invocation.succeeded is True
        assert invocation.capability_id == ALPHA_CAPABILITY_ID

        # The Tool Driver actually received the call's arguments.
        assert dict(tool_driver.calls[0].arguments) == {"value": "x"}

        # The Tool's result was fed back to the Provider as a "tool"
        # role message before the follow-up request.
        second_payload = transport.chat_payloads[1]
        tool_messages = [
            message
            for message in second_payload["messages"]
            if message["role"] == "tool"
        ]
        assert len(tool_messages) == 1
        fed_back = json.loads(tool_messages[0]["content"])
        assert fed_back["result"] == {"answer": 42}

    def test_json_encoded_string_arguments_are_accepted(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        """
        Some model templates emit `arguments` as a JSON-encoded string
        rather than a JSON object (see `wire.py`); the framework must
        still dispatch the call correctly.
        """

        tool_driver = _ScriptedToolDriver()
        tool_driver.queue_success("ok")
        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=tool_driver,
        )

        transport.queue_chat_response(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "tool_alpha",
                                "arguments": '{"value": "x"}',
                            }
                        }
                    ],
                },
                "done": True,
            }
        )
        transport.queue_chat_response(_assistant_message(content="done"))

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(_chat_goal("go", tools=(ALPHA_TOOL_SPEC,)),)
            )
        )

        assert response.succeeded
        assert dict(tool_driver.calls[0].arguments) == {"value": "x"}

    def test_recovers_tool_call_leaked_as_text(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        """
        The generic text-tool-call fallback (`text_tool_calls.py`)
        must recover a tool call even when a model's template leaks
        it into `content` instead of the native `tool_calls` field -
        for *any* tool name, not a hardcoded one.
        """

        tool_driver = _ScriptedToolDriver()
        tool_driver.queue_success("recovered")
        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=tool_driver,
        )

        transport.queue_chat_response(
            _assistant_message(
                content=(
                    "<function=tool_alpha>\n"
                    "<parameter=value>\nx\n</parameter>\n"
                    "</function>"
                )
            )
        )
        transport.queue_chat_response(_assistant_message(content="done"))

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(_chat_goal("go", tools=(ALPHA_TOOL_SPEC,)),)
            )
        )

        assert response.succeeded
        chat_response = response.results[0].response.outputs["result"]
        assert len(chat_response.tool_invocations) == 1
        assert chat_response.tool_invocations[0].succeeded is True
        assert dict(tool_driver.calls[0].arguments) == {"value": "x"}


# =====================================================================
# 3. Requests requiring MULTIPLE Tool-backed capabilities
# =====================================================================


class TestMultipleToolExecution:
    def test_two_simultaneous_tool_calls_in_one_turn(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        alpha_driver = _ScriptedToolDriver()
        alpha_driver.queue_success("alpha-result")
        beta_driver = _ScriptedToolDriver()
        beta_driver.queue_success("beta-result")

        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=alpha_driver,
        )
        pipeline.register_capability(
            capability_id=BETA_CAPABILITY_ID,
            tool_id=BETA_TOOL_ID,
            driver=beta_driver,
        )

        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[
                    _tool_call("tool_alpha", {"value": "a"}, call_id="c1"),
                    _tool_call("tool_beta", {"value": "b"}, call_id="c2"),
                ]
            )
        )
        transport.queue_chat_response(
            _assistant_message(content="Both are done.")
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    _chat_goal(
                        "do both",
                        tools=(ALPHA_TOOL_SPEC, BETA_TOOL_SPEC),
                    ),
                ),
            )
        )

        assert response.succeeded
        chat_response = response.results[0].response.outputs["result"]

        assert len(chat_response.tool_invocations) == 2
        names = [inv.tool_call.name for inv in chat_response.tool_invocations]
        assert names == ["tool_alpha", "tool_beta"]
        assert all(inv.succeeded for inv in chat_response.tool_invocations)

        # Ordering preserved: both tool results appear as separate
        # "tool" messages, in call order, before the follow-up request.
        second_payload = transport.chat_payloads[1]
        tool_messages = [
            message
            for message in second_payload["messages"]
            if message["role"] == "tool"
        ]
        assert len(tool_messages) == 2
        assert tool_messages[0]["name"] == "tool_alpha"
        assert tool_messages[1]["name"] == "tool_beta"

    def test_sequential_tool_calls_across_multiple_turns(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        """
        A model may also call one tool, see the result, and decide to
        call a second, different tool before finally answering.
        """

        alpha_driver = _ScriptedToolDriver()
        alpha_driver.queue_success("alpha-result")
        beta_driver = _ScriptedToolDriver()
        beta_driver.queue_success("beta-result")

        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=alpha_driver,
        )
        pipeline.register_capability(
            capability_id=BETA_CAPABILITY_ID,
            tool_id=BETA_TOOL_ID,
            driver=beta_driver,
        )

        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[_tool_call("tool_alpha", {"value": "a"})]
            )
        )
        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[_tool_call("tool_beta", {"value": "b"})]
            )
        )
        transport.queue_chat_response(
            _assistant_message(content="Both steps complete.")
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    _chat_goal(
                        "do both in sequence",
                        tools=(ALPHA_TOOL_SPEC, BETA_TOOL_SPEC),
                    ),
                ),
            )
        )

        assert response.succeeded
        chat_response = response.results[0].response.outputs["result"]
        assert [
            inv.tool_call.name for inv in chat_response.tool_invocations
        ] == ["tool_alpha", "tool_beta"]
        assert len(transport.chat_payloads) == 3


# =====================================================================
# 4. Conversation continuity
# =====================================================================


class TestConversationContinuity:
    def test_history_grows_correctly_after_a_tool_call_turn(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        tool_driver = _ScriptedToolDriver()
        tool_driver.queue_success("first-result")
        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=tool_driver,
        )

        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[_tool_call("tool_alpha", {"value": "x"})]
            )
        )
        transport.queue_chat_response(
            _assistant_message(content="Here is the first answer.")
        )

        pipeline.brain.handle(
            BrainRequest(
                goals=(_chat_goal("first question", tools=(ALPHA_TOOL_SPEC,)),)
            )
        )

        # First turn's request contains exactly the user message (no
        # prior history yet).
        first_payload = transport.chat_payloads[0]
        assert [m["role"] for m in first_payload["messages"]] == ["user"]

        # First turn's follow-up request (after the tool call)
        # contains user -> assistant(tool_calls) -> tool, in order.
        second_payload = transport.chat_payloads[1]
        assert [m["role"] for m in second_payload["messages"]] == [
            "user",
            "assistant",
            "tool",
        ]

    def test_follow_up_request_after_tool_execution_continues_working(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        """
        A second, independent chat Goal (simulating the next user
        turn in a session) must still work correctly after a prior
        turn already executed a tool - tool execution must not
        corrupt shared driver/resolver state.
        """

        tool_driver = _ScriptedToolDriver()
        tool_driver.queue_success("first-result")
        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=tool_driver,
        )

        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[_tool_call("tool_alpha", {"value": "x"})]
            )
        )
        transport.queue_chat_response(_assistant_message(content="First done."))

        first_response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    _chat_goal(
                        "first question",
                        tools=(ALPHA_TOOL_SPEC,),
                        goal_id="chat-1",
                    ),
                ),
            )
        )
        assert first_response.succeeded

        # Second, unrelated turn: no tool call needed this time.
        transport.queue_chat_response(
            _assistant_message(content="Second answer, no tool needed.")
        )

        second_response = pipeline.brain.handle(
            BrainRequest(
                goals=(_chat_goal("second question", goal_id="chat-2"),)
            )
        )

        assert second_response.succeeded
        chat_response = second_response.results[0].response.outputs["result"]
        assert chat_response.message.content == (
            "Second answer, no tool needed."
        )
        assert chat_response.tool_invocations == ()


# =====================================================================
# 5. Failure scenarios
# =====================================================================


class TestFailureScenarios:
    def test_tool_execution_failure_is_fed_back_and_recovered(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        tool_driver = _ScriptedToolDriver()
        tool_driver.queue_failure(RuntimeError("backend unavailable"))
        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=tool_driver,
        )

        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[_tool_call("tool_alpha", {"value": "x"})]
            )
        )
        transport.queue_chat_response(
            _assistant_message(content="I could not complete that action.")
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(_chat_goal("do it", tools=(ALPHA_TOOL_SPEC,)),)
            )
        )

        assert response.succeeded  # the chat turn itself still succeeds
        chat_response = response.results[0].response.outputs["result"]
        assert chat_response.tool_invocations[0].succeeded is False
        assert chat_response.message.content == (
            "I could not complete that action."
        )

        # The error was reported to the model as structured content,
        # not swallowed silently.
        second_payload = transport.chat_payloads[1]
        tool_message = next(
            m for m in second_payload["messages"] if m["role"] == "tool"
        )
        fed_back = json.loads(tool_message["content"])
        assert "error" in fed_back

    def test_unknown_tool_name_is_reported_without_calling_brain(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[_tool_call("nonexistent_tool", {})]
            )
        )
        transport.queue_chat_response(
            _assistant_message(content="That tool is not available.")
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(_chat_goal("do it", tools=(ALPHA_TOOL_SPEC,)),)
            )
        )

        assert response.succeeded
        chat_response = response.results[0].response.outputs["result"]
        invocation = chat_response.tool_invocations[0]
        assert invocation.succeeded is False
        assert invocation.capability_id is None

    def test_invalid_tool_call_missing_required_argument_still_dispatches(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        """
        The framework itself never validates a Tool's arguments
        against its JSON Schema (that is each Tool Driver's own
        responsibility) - an "invalid" call is simply dispatched with
        whatever arguments were supplied, and the Tool Driver decides
        whether that is acceptable.
        """

        tool_driver = _ScriptedToolDriver()
        tool_driver.queue_failure(ValueError("missing required 'value'"))
        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=tool_driver,
        )

        transport.queue_chat_response(
            _assistant_message(tool_calls=[_tool_call("tool_alpha", {})])
        )
        transport.queue_chat_response(
            _assistant_message(content="I was missing required information.")
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(_chat_goal("do it", tools=(ALPHA_TOOL_SPEC,)),)
            )
        )

        assert response.succeeded
        assert tool_driver.calls[0].arguments == {}
        chat_response = response.results[0].response.outputs["result"]
        assert chat_response.tool_invocations[0].succeeded is False

    def test_provider_failure_propagates_as_a_planning_failure(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        from parika.providers.ollama.exceptions import OllamaConnectionError

        transport.queue_chat_error(OllamaConnectionError("connection refused"))

        response = pipeline.brain.handle(
            BrainRequest(goals=(_chat_goal("hello"),))
        )

        assert not response.succeeded
        assert response.results[0].status is TaskStatus.FAILED
        assert response.results[0].failure is not None

    def test_provider_timeout_is_reported_meaningfully(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        from parika.providers.ollama.exceptions import OllamaTimeoutError

        transport.queue_chat_error(OllamaTimeoutError("request timed out"))

        response = pipeline.brain.handle(
            BrainRequest(goals=(_chat_goal("hello"),))
        )

        assert not response.succeeded
        failure = response.results[0].failure
        assert failure is not None

        root_cause: BaseException = failure
        while root_cause.__cause__ is not None:
            root_cause = root_cause.__cause__

        assert "timed out" in str(root_cause)

    def test_exceeding_max_tool_iterations_reports_a_clear_error(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        tool_driver = _ScriptedToolDriver()
        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=tool_driver,
        )

        # Genuinely different arguments on every turn (see
        # `chat_loop.NO_OP_REPEAT_LIMIT`'s own docstring) so neither
        # deterministic-call caching nor no-op turn detection ever
        # short-circuits this loop - it is `max_tool_iterations`
        # itself, and nothing else, that is under test here.
        for index in range(3):
            transport.queue_chat_response(
                _assistant_message(
                    tool_calls=[
                        _tool_call("tool_alpha", {"value": f"x{index}"})
                    ]
                )
            )
            tool_driver.queue_success("still going")

        def _build(resolution, model) -> ProviderRequest:  # noqa: ANN001
            return OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="loop"),),
                tools=(ALPHA_TOOL_SPEC,),
                max_tool_iterations=2,
            )

        goal = Goal(
            id="chat-loop",
            capability_id=CHAT_CAPABILITY_ID,
            inputs={"message": "loop"},
            provider_request_builder=_build,
        )

        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert not response.succeeded
        assert response.results[0].status is TaskStatus.FAILED

        # `GoalResult.failure` is a generic `TaskExecutionError` by
        # design (see `Provider_Tool_Calling.md`'s Error Reporting
        # section); the specific root cause is preserved via standard
        # Python exception chaining (`__cause__`), not the top-level
        # message.
        failure = response.results[0].failure
        assert failure is not None

        root_cause: BaseException = failure
        while root_cause.__cause__ is not None:
            root_cause = root_cause.__cause__

        assert "tool-calling iterations" in str(root_cause)

    def test_partial_multi_tool_execution_one_succeeds_one_fails(
        self, pipeline: _Pipeline, transport: _FakeOllamaTransport
    ) -> None:
        alpha_driver = _ScriptedToolDriver()
        alpha_driver.queue_success("alpha-ok")
        beta_driver = _ScriptedToolDriver()
        beta_driver.queue_failure(RuntimeError("beta backend down"))

        pipeline.register_capability(
            capability_id=ALPHA_CAPABILITY_ID,
            tool_id=ALPHA_TOOL_ID,
            driver=alpha_driver,
        )
        pipeline.register_capability(
            capability_id=BETA_CAPABILITY_ID,
            tool_id=BETA_TOOL_ID,
            driver=beta_driver,
        )

        transport.queue_chat_response(
            _assistant_message(
                tool_calls=[
                    _tool_call("tool_alpha", {"value": "a"}, call_id="c1"),
                    _tool_call("tool_beta", {"value": "b"}, call_id="c2"),
                ]
            )
        )
        transport.queue_chat_response(
            _assistant_message(
                content="Alpha succeeded; beta failed, here is what I have."
            )
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    _chat_goal(
                        "do both", tools=(ALPHA_TOOL_SPEC, BETA_TOOL_SPEC)
                    ),
                ),
            )
        )

        assert response.succeeded
        chat_response = response.results[0].response.outputs["result"]
        results_by_name = {
            inv.tool_call.name: inv.succeeded
            for inv in chat_response.tool_invocations
        }
        assert results_by_name == {"tool_alpha": True, "tool_beta": False}
