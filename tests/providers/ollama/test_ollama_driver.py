"""
Unit tests for OllamaProviderDriver.

Model discovery, health, generation, and chat are exercised against a
`FakeOllamaTransport` so no real network access is required. Tool
calling is exercised against a real `Brain`/`Planner`/`TaskManager`/
`CapabilityExecutor`/`ToolManager` stack (the same shape used by
`tests/core/brain/test_brain.py`), with only the innermost Tool driver
faked, so the "call Brain correctly, never bypass Planner" requirement
is actually verified end to end rather than assumed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from parika.core.brain.brain import Brain
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
from parika.providers.ollama.driver import OllamaProviderDriver
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.providers.ollama.exceptions import (
    OllamaModelNotFoundError,
    OllamaRequestError,
    OllamaResponseError,
    OllamaToolCallError,
)
from parika.providers.ollama.messages import OllamaMessage, OllamaToolSpec
from parika.providers.ollama.requests import (
    OllamaChatRequest,
    OllamaGenerateRequest,
)
from parika.providers.ollama.responses import OllamaChatResponse
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest


class FakeOllamaTransport:
    """
    Deterministic OllamaTransport test double.

    Queued items are consumed in FIFO order as the driver issues
    requests, so tests can script multi-turn chat conversations
    (e.g. a tool-calling turn followed by a final-answer turn) by
    queuing one response per expected request.
    """

    def __init__(self) -> None:
        self.json_calls: list[
            tuple[str, str, dict[str, Any] | None, float]
        ] = []
        self.stream_calls: list[
            tuple[str, str, dict[str, Any] | None, float]
        ] = []

        self._json_queue: list[dict[str, Any] | Exception] = []
        self._stream_queue: list[list[dict[str, Any]] | Exception] = []

    def queue_json(self, response: dict[str, Any] | Exception) -> None:
        self._json_queue.append(response)

    def queue_stream(self, chunks: list[dict[str, Any]] | Exception) -> None:
        self._stream_queue.append(chunks)

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        self.json_calls.append(
            (method, url, dict(payload) if payload else None, timeout)
        )

        item = self._json_queue.pop(0)

        if isinstance(item, Exception):
            raise item

        return item

    def stream_lines(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> Iterator[dict[str, Any]]:
        self.stream_calls.append(
            (method, url, dict(payload) if payload else None, timeout)
        )

        item = self._stream_queue.pop(0)

        if isinstance(item, Exception):
            raise item

        yield from item


def make_model(model_id: str = "qwen3:8b") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        execution_features=frozenset({ModelExecutionFeature.TOOL_CALLING}),
    )


@pytest.fixture
def transport() -> FakeOllamaTransport:
    return FakeOllamaTransport()


@pytest.fixture
def ollama_driver(
    transport: FakeOllamaTransport,
    logger: Logger,
) -> OllamaProviderDriver:
    return OllamaProviderDriver(
        transport=transport,
        logger=logger,
        base_url="http://localhost:11434",
        connect_timeout_seconds=1.0,
        request_timeout_seconds=5.0,
    )


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


class _BrainStack:
    """Real Brain + Planner + TaskManager + ToolManager stack."""

    def __init__(self) -> None:
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
        task_manager = TaskManager(
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
        )
        self.brain = Brain(
            planner=planner, task_manager=task_manager, logger=logger
        )

    def register_tool(
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


# ---------------------------------------------------------------------
# discover_models() / list_models()
# ---------------------------------------------------------------------


class TestListModels:
    def test_builds_provider_models_from_tags_and_show(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            {
                "models": [
                    {
                        "name": "qwen3:8b",
                        "details": {
                            "family": "qwen3",
                            "parameter_size": "8.2B",
                            "quantization_level": "Q4_K_M",
                        },
                    }
                ]
            }
        )
        transport.queue_json(
            {
                "capabilities": ["completion", "tools"],
                "model_info": {"qwen3.context_length": 40960},
            }
        )

        models = ollama_driver.list_models()

        assert len(models) == 1
        model = models[0]
        assert model.id == "qwen3:8b"
        assert "qwen3" in (model.description or "")
        assert model.limits.context_window == 40960
        assert model.metadata["deployment_type"] == "local"
        assert model.metadata["estimated_latency_ms"] > 0

    def test_reasoning_capable_models_get_higher_latency_estimate(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            {"models": [{"name": "reasoning-model", "details": {"parameter_size": "8B"}}]}
        )
        transport.queue_json({"capabilities": ["completion", "thinking"]})

        models = ollama_driver.list_models()

        transport.queue_json(
            {"models": [{"name": "plain-model", "details": {"parameter_size": "8B"}}]}
        )
        transport.queue_json({"capabilities": ["completion"]})

        plain_models = ollama_driver.list_models()

        assert models[0].metadata["estimated_latency_ms"] > (
            plain_models[0].metadata["estimated_latency_ms"]
        )

    def test_missing_show_details_still_returns_model(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json({"models": [{"name": "qwen3:8b"}]})
        transport.queue_json(OllamaResponseError("boom"))

        models = ollama_driver.list_models()

        assert len(models) == 1
        assert models[0].id == "qwen3:8b"

    def test_no_models_key_returns_empty_tuple(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json({})

        assert ollama_driver.list_models() == ()

    def test_discover_models_delegates_to_list_models(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json({"models": []})

        assert ollama_driver.discover_models() == ()


# ---------------------------------------------------------------------
# health() / availability() / check_health()
# ---------------------------------------------------------------------


class TestHealth:
    def test_health_available_on_success(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json({"version": "0.32.3"})

        health = ollama_driver.health()

        assert health.available is True
        assert health.latency_ms is not None
        assert "0.32.3" in (health.message or "")

    def test_health_unavailable_on_connection_failure(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        from parika.providers.ollama.exceptions import OllamaConnectionError

        transport.queue_json(OllamaConnectionError("refused"))

        health = ollama_driver.health()

        assert health.available is False
        assert "refused" in (health.message or "")

    def test_check_health_delegates_to_health(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json({"version": "0.1.0"})

        assert ollama_driver.check_health().available is True

    def test_availability_returns_bool(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json({"version": "0.1.0"})

        assert ollama_driver.availability() is True


# ---------------------------------------------------------------------
# execute() dispatch
# ---------------------------------------------------------------------


class TestExecuteDispatch:
    def test_dispatches_chat_request_to_chat(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            {"message": {"role": "assistant", "content": "hi"}, "done": True}
        )

        response = ollama_driver.execute(
            make_model(),
            OllamaChatRequest(messages=(OllamaMessage(role="user", content="hi"),)),
        )

        assert response.message.content == "hi"

    def test_dispatches_generic_chat_request_to_chat_and_returns_chat_result(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        """
        The provider-independent `ChatRequest` (built by every
        provider-independent layer -- Interfaces, Modules) is
        converted to `OllamaChatRequest` internally, and the
        resulting `OllamaChatResponse` is converted back into a
        provider-independent `ChatResult` -- callers outside this
        provider package never see either concrete Ollama type.
        """

        transport.queue_json(
            {"message": {"role": "assistant", "content": "hi"}, "done": True}
        )

        response = ollama_driver.execute(
            make_model(),
            ChatRequest(messages=(ChatMessage(role="user", content="hi"),)),
        )

        assert isinstance(response, ChatResult)
        assert not isinstance(response, OllamaChatResponse)
        assert response.message.content == "hi"

    def test_dispatches_generate_request_to_generate(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json({"response": "42", "done": True})

        response = ollama_driver.execute(
            make_model(), OllamaGenerateRequest(prompt="what is the answer?")
        )

        assert response.text == "42"

    def test_unsupported_request_type_raises(self, ollama_driver) -> None:
        with pytest.raises(OllamaRequestError):
            ollama_driver.execute(make_model(), ProviderRequest())


# ---------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------


class TestGenerate:
    def test_non_streamed_generate(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            {
                "response": "The answer is 4.",
                "done": True,
                "eval_count": 5,
            }
        )

        response = ollama_driver.generate(
            make_model(), OllamaGenerateRequest(prompt="2+2?")
        )

        assert response.text == "The answer is 4."
        assert response.eval_count == 5
        method, url, payload, _ = transport.json_calls[0]
        assert method == "POST"
        assert url.endswith("/api/generate")
        assert payload["stream"] is False

    def test_streamed_generate_invokes_on_token(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_stream(
            [
                {"response": "Hel", "done": False},
                {"response": "lo", "done": False},
                {"response": "", "done": True, "eval_count": 2},
            ]
        )

        fragments: list[str] = []

        response = ollama_driver.generate(
            make_model(),
            OllamaGenerateRequest(prompt="say hello", on_token=fragments.append),
        )

        assert fragments == ["Hel", "lo"]
        assert response.text == "Hello"
        assert response.eval_count == 2

    def test_model_not_found_is_translated(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            OllamaResponseError('model "missing" not found, try pulling it')
        )

        with pytest.raises(OllamaModelNotFoundError):
            ollama_driver.generate(
                make_model("missing"), OllamaGenerateRequest(prompt="hi")
            )


# ---------------------------------------------------------------------
# chat() - no tool calling
# ---------------------------------------------------------------------


class TestReasoningPassthrough:
    def test_generate_sends_think_field_when_reasoning_is_set(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        from dataclasses import replace

        transport.queue_json({"response": "ok", "done": True})

        request = OllamaGenerateRequest(prompt="hi")
        request = replace(
            request, options=replace(request.options, reasoning=True)
        )

        ollama_driver.generate(make_model(), request)

        payload = transport.json_calls[0][2]
        assert payload["think"] is True

    def test_generate_omits_think_field_when_reasoning_is_none(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json({"response": "ok", "done": True})

        ollama_driver.generate(make_model(), OllamaGenerateRequest(prompt="hi"))

        payload = transport.json_calls[0][2]
        assert "think" not in payload

    def test_chat_sends_think_field_when_reasoning_is_set(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        from dataclasses import replace

        transport.queue_json(
            {"message": {"role": "assistant", "content": "ok"}, "done": True}
        )

        request = OllamaChatRequest(
            messages=(OllamaMessage(role="user", content="hi"),)
        )
        request = replace(
            request, options=replace(request.options, reasoning=False)
        )

        ollama_driver.chat(make_model(), request)

        payload = transport.json_calls[0][2]
        assert payload["think"] is False


class TestChatWithoutTools:
    def test_returns_final_answer_directly(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            {
                "message": {"role": "assistant", "content": "Hi there."},
                "done": True,
            }
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hello"),)
            ),
        )

        assert response.message.content == "Hi there."
        assert response.tool_invocations == ()

    def test_streamed_chat_invokes_on_token_for_final_answer(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_stream(
            [
                {"message": {"content": "Hel"}, "done": False},
                {"message": {"content": "lo!"}, "done": False},
                {"message": {"content": ""}, "done": True},
            ]
        )

        fragments: list[str] = []

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),),
                on_token=fragments.append,
            ),
        )

        assert fragments == ["Hel", "lo!"]
        assert response.message.content == "Hello!"


class TestReasoningMarkupSuppression:
    """
    Regression tests for Issue 9: a model's own leaked reasoning
    narration ("I need to search...", "Let me check...") - wrapped in
    a `<think>...</think>`/`<reasoning>...</reasoning>` block by its
    chat template - must never be shown to the user, live or in the
    final answer, regardless of whether tools were offered for this
    turn at all.
    """

    def test_think_block_never_reaches_on_token_without_tools(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_stream(
            [
                {
                    "message": {
                        "content": "<think>I need to check the weather API.</think>"
                    },
                    "done": False,
                },
                {"message": {"content": "It's sunny today."}, "done": False},
                {"message": {"content": ""}, "done": True},
            ]
        )

        fragments: list[str] = []

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="weather?"),),
                on_token=fragments.append,
            ),
        )

        streamed_text = "".join(fragments)

        assert streamed_text == "It's sunny today."
        assert "<think>" not in streamed_text
        assert response.message.content == "It's sunny today."

    def test_reasoning_block_stripped_from_non_streamed_final_answer(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "<reasoning>Let me think about this "
                        "carefully.</reasoning>The capital is Paris."
                    ),
                },
                "done": True,
            }
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(
                    OllamaMessage(
                        role="user", content="capital of France?"
                    ),
                )
            ),
        )

        assert response.message.content == "The capital is Paris."

    def test_think_block_split_across_multiple_chunks_is_suppressed(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_stream(
            [
                {"message": {"content": "<thi"}, "done": False},
                {"message": {"content": "nk>Let me "}, "done": False},
                {"message": {"content": "search for that.</think>"}, "done": False},
                {"message": {"content": "Here is the answer."}, "done": False},
                {"message": {"content": ""}, "done": True},
            ]
        )

        fragments: list[str] = []

        ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),),
                on_token=fragments.append,
            ),
        )

        streamed_text = "".join(fragments)

        assert streamed_text == "Here is the answer."

    def test_ordinary_streaming_without_tools_or_reasoning_is_unaffected(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_stream(
            [
                {"message": {"content": "Just"}, "done": False},
                {"message": {"content": " a normal answer."}, "done": False},
                {"message": {"content": ""}, "done": True},
            ]
        )

        fragments: list[str] = []

        ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),),
                on_token=fragments.append,
            ),
        )

        assert fragments == ["Just", " a normal answer."]


class TestStreamedLeakedMarkupSuppression:
    """
    Regression tests for the streaming protocol filter
    (`stream_filter.ToolMarkupStreamFilter`): leaked tool-call
    template markup must never reach a streaming caller's `on_token`,
    while ordinary streamed text - including when tools are also
    available - keeps flowing live exactly as before.
    """

    def test_leaked_markup_never_reaches_on_token(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        stack = _BrainStack()
        tool_driver = _ScriptedToolDriver()
        tool_driver.succeed_with(
            ToolResponse(
                result=({"title": "PARIKA"},), attributes={"query": "parika"}
            )
        )
        stack.register_tool(
            capability_id="web.search", tool_id="tool.web_search", driver=tool_driver
        )
        ollama_driver.bind_brain(stack.brain)

        # The model leaks XML-style tool-call markup as streamed
        # content fragments instead of populating native `tool_calls`
        # - reproducing the qwen3-coder quirk `text_tool_calls.py`
        # documents - split across several chunks so the markup hint
        # itself spans chunk boundaries.
        transport.queue_stream(
            [
                {"message": {"content": "<funct"}, "done": False},
                {"message": {"content": "ion=web_search>"}, "done": False},
                {
                    "message": {
                        "content": "<parameter=query>parika</parameter>"
                    },
                    "done": False,
                },
                {
                    "message": {"content": "</function>\n</tool_call>"},
                    "done": False,
                },
                {"message": {"content": ""}, "done": True},
            ]
        )
        transport.queue_stream(
            [
                {"message": {"content": "PARIKA is"}, "done": False},
                {"message": {"content": " an intelligence kernel."}, "done": False},
                {"message": {"content": ""}, "done": True},
            ]
        )

        fragments: list[str] = []

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(
                    OllamaMessage(role="user", content="search for parika"),
                ),
                tools=(WEB_SEARCH_SPEC,),
                on_token=fragments.append,
            ),
        )

        streamed_text = "".join(fragments)

        assert streamed_text == "PARIKA is an intelligence kernel."
        assert "<function=" not in streamed_text
        assert "<tool_call>" not in streamed_text
        assert "<parameter=" not in streamed_text

        assert response.message.content == "PARIKA is an intelligence kernel."
        assert len(response.tool_invocations) == 1
        assert response.tool_invocations[0].succeeded is True
        assert response.tool_invocations[0].tool_call.name == "web_search"

    def test_normal_streaming_with_tools_available_is_unaffected(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_stream(
            [
                {"message": {"content": "The"}, "done": False},
                {"message": {"content": " sky is blue."}, "done": False},
                {"message": {"content": ""}, "done": True},
            ]
        )

        fragments: list[str] = []

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(
                    OllamaMessage(
                        role="user", content="why is the sky blue?"
                    ),
                ),
                tools=(WEB_SEARCH_SPEC,),
                on_token=fragments.append,
            ),
        )

        assert fragments == ["The", " sky is blue."]
        assert response.message.content == "The sky is blue."
        assert response.tool_invocations == ()

    def test_preamble_before_leaked_markup_is_never_streamed(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        """
        Regression test for Phase 1 Item 3 ("Fix Provider
        Conversation Loop"): a preamble preceding leaked tool-call
        markup must never reach the caller's `on_token` at all, even
        though it is genuine, non-markup text - because whether this
        turn resolves to a tool call is only known once the full
        response (and its markup-recovery parse) has completed. Since
        this turn *does* resolve to a tool call, that preamble would
        otherwise reach the caller as a superseded "response" once
        the follow-up turn's real final answer ("Done.") arrives -
        exactly the "leaked preamble"/"concatenated response" bug
        this fix addresses. Only "Done." - the genuine, tool-call-free
        final answer - is ever streamed.
        """

        stack = _BrainStack()
        tool_driver = _ScriptedToolDriver()
        tool_driver.succeed_with(
            ToolResponse(result=({"title": "PARIKA"},), attributes={})
        )
        stack.register_tool(
            capability_id="web.search", tool_id="tool.web_search", driver=tool_driver
        )
        ollama_driver.bind_brain(stack.brain)

        transport.queue_stream(
            [
                {
                    "message": {
                        "content": (
                            "Sure, let me look that up. "
                            "<function=web_search><parameter=query>"
                            "parika</parameter></function></tool_call>"
                        )
                    },
                    "done": False,
                },
                {"message": {"content": ""}, "done": True},
            ]
        )
        transport.queue_stream(
            [
                {"message": {"content": "Done."}, "done": False},
                {"message": {"content": ""}, "done": True},
            ]
        )

        fragments: list[str] = []

        ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(
                    OllamaMessage(role="user", content="search for parika"),
                ),
                tools=(WEB_SEARCH_SPEC,),
                on_token=fragments.append,
            ),
        )

        streamed_text = "".join(fragments)

        assert streamed_text == "Done."
        assert "Sure, let me look" not in streamed_text
        assert "<function=" not in streamed_text


class TestDuplicateResponsePrevention:
    """
    Regression tests for Priority 3: a tool-calling turn's
    `OllamaMessage` must never carry directly displayable content -
    whether from native `tool_calls` or from markup recovery - so
    exactly one assistant response is ever produced per chat turn.
    """

    def test_native_tool_calls_with_accompanying_content_are_cleared(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        stack = _BrainStack()
        tool_driver = _ScriptedToolDriver()
        tool_driver.succeed_with(
            ToolResponse(result=({"title": "PARIKA"},), attributes={})
        )
        stack.register_tool(
            capability_id="web.search", tool_id="tool.web_search", driver=tool_driver
        )
        ollama_driver.bind_brain(stack.brain)

        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    # Some model templates emit a preamble alongside
                    # native `tool_calls`; PARIKA never treats this
                    # as a second, superseded "response".
                    "content": "Let me search for that.",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {"query": "parika"},
                            }
                        }
                    ],
                },
                "done": True,
            }
        )
        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "PARIKA is an intelligence kernel.",
                },
                "done": True,
            }
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(
                    OllamaMessage(role="user", content="search for parika"),
                ),
                tools=(WEB_SEARCH_SPEC,),
            ),
        )

        assert response.message.content == (
            "PARIKA is an intelligence kernel."
        )
        assert len(response.tool_invocations) == 1


# ---------------------------------------------------------------------
# chat() - tool calling through a real Brain/Planner/ToolManager stack
# ---------------------------------------------------------------------


WEB_SEARCH_SPEC = OllamaToolSpec(
    name="web_search",
    description="Search the web.",
    capability_id="web.search",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
)


class TestChatToolCalling:
    def test_successful_tool_call_is_resolved_through_brain(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        stack = _BrainStack()
        tool_driver = _ScriptedToolDriver()
        tool_driver.succeed_with(
            ToolResponse(result=({"title": "PARIKA"},), attributes={"query": "parika"})
        )
        stack.register_tool(
            capability_id="web.search", tool_id="tool.web_search", driver=tool_driver
        )
        ollama_driver.bind_brain(stack.brain)

        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {"query": "parika"},
                            }
                        }
                    ],
                },
                "done": True,
            }
        )
        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "PARIKA is an intelligence kernel.",
                },
                "done": True,
            }
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(
                    OllamaMessage(role="user", content="search for parika"),
                ),
                tools=(WEB_SEARCH_SPEC,),
            ),
        )

        assert response.message.content == (
            "PARIKA is an intelligence kernel."
        )
        assert len(response.tool_invocations) == 1

        invocation = response.tool_invocations[0]
        assert invocation.succeeded is True
        assert invocation.capability_id == "web.search"
        assert tool_driver.calls[0].arguments["query"] == "parika"

        # The tool result was fed back to the model as a "tool" message.
        second_call_payload = transport.json_calls[1][2]
        tool_messages = [
            message
            for message in second_call_payload["messages"]
            if message["role"] == "tool"
        ]
        assert len(tool_messages) == 1
        fed_back = json.loads(tool_messages[0]["content"])
        assert fed_back["result"] == [{"title": "PARIKA"}]

    def test_failing_tool_call_feeds_error_back_and_model_still_answers(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        stack = _BrainStack()
        tool_driver = _ScriptedToolDriver()
        tool_driver.fail_with(RuntimeError("network unreachable"))
        stack.register_tool(
            capability_id="web.search", tool_id="tool.web_search", driver=tool_driver
        )
        ollama_driver.bind_brain(stack.brain)

        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "web_search", "arguments": {"query": "x"}}}
                    ],
                },
                "done": True,
            }
        )
        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "I could not search the web right now.",
                },
                "done": True,
            }
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="search"),),
                tools=(WEB_SEARCH_SPEC,),
            ),
        )

        assert response.tool_invocations[0].succeeded is False
        assert response.message.content == (
            "I could not search the web right now."
        )

    def test_unknown_tool_name_reports_error_without_calling_brain(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        stack = _BrainStack()
        ollama_driver.bind_brain(stack.brain)

        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "unknown_tool", "arguments": {}}}
                    ],
                },
                "done": True,
            }
        )
        transport.queue_json(
            {"message": {"role": "assistant", "content": "ok"}, "done": True}
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),),
                tools=(WEB_SEARCH_SPEC,),
            ),
        )

        invocation = response.tool_invocations[0]
        assert invocation.succeeded is False
        assert invocation.capability_id is None
        assert "Unknown tool" in invocation.content

    def test_tool_call_without_bound_brain_reports_error(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "web_search", "arguments": {"query": "x"}}}
                    ],
                },
                "done": True,
            }
        )
        transport.queue_json(
            {"message": {"role": "assistant", "content": "ok"}, "done": True}
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),),
                tools=(WEB_SEARCH_SPEC,),
            ),
        )

        invocation = response.tool_invocations[0]
        assert invocation.succeeded is False
        assert "no Brain is bound" in invocation.content

    def test_exceeding_max_tool_iterations_raises(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        """
        Genuinely different arguments on every turn (see
        `chat_loop.NO_OP_REPEAT_LIMIT`'s own docstring) so neither
        deterministic-call caching nor no-op turn detection ever
        short-circuits this loop - it is `max_tool_iterations` itself,
        and nothing else, that is under test here.
        """

        stack = _BrainStack()
        tool_driver = _ScriptedToolDriver()
        tool_driver.succeed_with(ToolResponse(result=()))
        stack.register_tool(
            capability_id="web.search", tool_id="tool.web_search", driver=tool_driver
        )
        ollama_driver.bind_brain(stack.brain)

        for query in ("x0", "x1", "x2"):
            transport.queue_json(
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "web_search",
                                    "arguments": {"query": query},
                                }
                            }
                        ],
                    },
                    "done": True,
                }
            )

        with pytest.raises(OllamaToolCallError):
            ollama_driver.chat(
                make_model(),
                OllamaChatRequest(
                    messages=(OllamaMessage(role="user", content="hi"),),
                    tools=(WEB_SEARCH_SPEC,),
                    max_tool_iterations=2,
                ),
            )


class TestEmptyFinalResponseRetry:
    """
    Some models occasionally produce a genuinely blank final answer
    (no tool call, no content) - an observed, non-deterministic
    sampling outcome. The driver retries this a small, bounded number
    of times before accepting it, without consuming any of
    `max_tool_iterations`' own budget.
    """

    def test_retries_once_on_empty_response_and_succeeds(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        transport.queue_json(
            {"message": {"role": "assistant", "content": ""}, "done": True}
        )
        transport.queue_json(
            {
                "message": {"role": "assistant", "content": "Real answer."},
                "done": True,
            }
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),)
            ),
        )

        assert response.message.content == "Real answer."
        assert len(transport.json_calls) == 2

    def test_gives_up_after_exhausting_retries_and_returns_empty(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        empty_chunk = {
            "message": {"role": "assistant", "content": ""},
            "done": True,
        }

        transport.queue_json(empty_chunk)
        transport.queue_json(empty_chunk)

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),)
            ),
        )

        assert response.message.content == ""
        # Exactly the initial call plus the bounded retry budget - no
        # more, no less.
        assert len(transport.json_calls) == 2

    def test_does_not_consume_max_tool_iterations_budget(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        """
        An empty-response retry on one turn must not count against
        the separate tool-calling iteration budget: a model may still
        use its *full* `max_tool_iterations` afterward.
        """

        transport.queue_json(
            {"message": {"role": "assistant", "content": ""}, "done": True}
        )
        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {"query": "x"},
                            }
                        }
                    ],
                },
                "done": True,
            }
        )
        transport.queue_json(
            {
                "message": {"role": "assistant", "content": "Done after tool."},
                "done": True,
            }
        )

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),),
                tools=(WEB_SEARCH_SPEC,),
                max_tool_iterations=1,
            ),
        )

        assert response.message.content == "Done after tool."
        # The tool call was still processed (no Brain bound here, so
        # it reports as failed, but it *was* dispatched) - proving the
        # earlier empty-response retry did not eat into this turn's
        # tool-calling budget.
        assert len(response.tool_invocations) == 1

    def test_a_tool_call_produced_during_retry_is_still_processed(
        self, ollama_driver, transport: FakeOllamaTransport
    ) -> None:
        """
        If the retried attempt decides to call a tool instead of
        answering, that tool call must still be honored normally.
        """

        transport.queue_json(
            {"message": {"role": "assistant", "content": ""}, "done": True}
        )
        transport.queue_json(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {"query": "x"},
                            }
                        }
                    ],
                },
                "done": True,
            }
        )
        transport.queue_json(
            {
                "message": {"role": "assistant", "content": "Final."},
                "done": True,
            }
        )

        stack = _BrainStack()
        tool_driver = _ScriptedToolDriver()
        tool_driver.succeed_with(ToolResponse(result="ok"))
        stack.register_tool(
            capability_id="web.search", tool_id="tool.web_search", driver=tool_driver
        )
        ollama_driver.bind_brain(stack.brain)

        response = ollama_driver.chat(
            make_model(),
            OllamaChatRequest(
                messages=(OllamaMessage(role="user", content="hi"),),
                tools=(WEB_SEARCH_SPEC,),
            ),
        )

        assert response.message.content == "Final."
        assert len(response.tool_invocations) == 1
        assert response.tool_invocations[0].succeeded is True
