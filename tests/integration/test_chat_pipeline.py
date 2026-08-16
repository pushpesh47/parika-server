"""
End-to-end integration tests for the complete chat/tool-calling
pipeline:

    Brain -> Planner -> TaskManager -> CapabilityExecutor ->
    ProviderManager -> Ollama Provider -> (tool calling) -> Brain ->
    Planner -> TaskManager -> CapabilityExecutor -> ToolManager ->
    Web Search Tool

These tests exercise the full, real Core stack together with the real
Chat Module, Web Search Module, and Ollama provider driver. Only the
outermost network boundary (the Ollama `OllamaTransport`, and the Web
Search Tool's `HttpTransport`) is replaced with deterministic fakes so
the suite never depends on real network access or a running Ollama
server, while every other PARIKA component in between is real.
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
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.brain.brain_request import BrainRequest
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.request import ProviderRequest
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.chat.driver import CHAT_CAPABILITY_ID, ChatModuleDriver
from parika.modules.chat.manifest import CHAT_MODULE_ID, create_chat_module
from parika.modules.web_search.driver import WebSearchModuleDriver
from parika.modules.web_search.manifest import (
    WEB_SEARCH_MODULE_ID,
    create_web_search_module,
)
from parika.providers.ollama.driver import OllamaProviderDriver
from parika.providers.ollama.manifest import (
    OLLAMA_PROVIDER_ID,
    create_ollama_provider,
)
from parika.providers.ollama.messages import OllamaMessage, OllamaToolSpec
from parika.providers.ollama.requests import OllamaChatRequest
from parika.tools.web_search.manifest import (
    WEB_SEARCH_CAPABILITY_ID,
    WEB_SEARCH_TOOL_AFFORDANCE,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider_model import ProviderModel
from parika.tools.web_search.exceptions import WebSearchNetworkError
from parika.tools.web_search.transport import HttpResponse

WEB_SEARCH_TOOL_SPEC = OllamaToolSpec(
    name="web_search",
    description=WEB_SEARCH_TOOL_AFFORDANCE["description"],
    capability_id=WEB_SEARCH_CAPABILITY_ID,
    parameters=WEB_SEARCH_TOOL_AFFORDANCE["parameters"],
)
"""
Test-local reconstruction of the `web.search` tool spec from the Web
Search Tool's own schema (`parika.tools.web_search.manifest.
WEB_SEARCH_TOOL_AFFORDANCE`) -- AI Context Engineering builds this
dynamically at runtime (see `parika.interfaces.ai_context.
tool_context`), so this fixture exists only to give this test's own
`_provider_request_builder` a concrete `tools` tuple to advertise.
"""

SAMPLE_RESULTS_HTML = """
<div class="g">
  <a href="https://example.com/parika">
    <h3>PARIKA Official Site</h3>
  </a>
  <div class="VwiC3b">Official homepage of PARIKA.</div>
</div>
"""
"""
Shaped for `GoogleHtmlSearchBackend` - the default provider (see
`config.DEFAULT_PROVIDER`) this pipeline exercises when
`WebSearchModuleDriver` is constructed without an explicit
`Configuration`.
"""


class _FakeHttpTransport:
    """Deterministic HttpTransport for the Web Search Tool."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._responses: list[HttpResponse | Exception] = []

    def queue_response(self, response: HttpResponse) -> None:
        self._responses.append(response)

    def queue_error(self, error: Exception) -> None:
        self._responses.append(error)

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        self.calls.append(url)
        item = self._responses.pop(0)

        if isinstance(item, Exception):
            raise item

        return item


def _search_response(body: str = SAMPLE_RESULTS_HTML) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        url="https://www.google.com/search?q=parika&num=5",
        headers={"Content-Type": "text/html"},
        body=body.encode("utf-8"),
    )


class _FakeOllamaTransport:
    """Deterministic OllamaTransport standing in for a real Ollama server."""

    def __init__(self) -> None:
        self._chat_queue: list[dict[str, Any]] = []
        self.chat_payloads: list[dict[str, Any]] = []

    def queue_chat_response(self, response: dict[str, Any]) -> None:
        self._chat_queue.append(response)

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
            return self._chat_queue.pop(0)

        return {}

    def stream_lines(
        self, method: str, url: str, *, payload, timeout
    ) -> Iterator[dict[str, Any]]:
        return iter(())


class Pipeline:
    """Bundles the full, real Core stack plus every built-in Module."""

    def __init__(
        self,
        *,
        ollama_transport: _FakeOllamaTransport,
        http_transport: _FakeHttpTransport,
    ) -> None:
        configuration = Configuration()
        logger = Logger(configuration)
        event_bus = EventBus(logger=logger)

        capability_registry = CapabilityRegistry(
            event_bus=event_bus, logger=logger
        )
        capability_resolver = CapabilityResolver(
            capability_registry=capability_registry, logger=logger
        )
        resource_manager = ResourceManager(
            configuration=configuration, logger=logger
        )
        policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
        provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)
        module_manager = ModuleManager(
            configuration=configuration, event_bus=event_bus, logger=logger
        )

        capability_executor = CapabilityExecutor(
            event_bus=event_bus,
            logger=logger,
            tool_manager=tool_manager,
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
            tool_manager=tool_manager,
            logger=logger,
        )
        self.brain = Brain(
            planner=planner, task_manager=self.task_manager, logger=logger
        )

        web_search_driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=http_transport,
            backoff_seconds=0.0,
        )
        module_manager.register(create_web_search_module(web_search_driver))
        module_manager.load(WEB_SEARCH_MODULE_ID)

        chat_driver = ChatModuleDriver(
            capability_registry=capability_registry, logger=logger
        )
        module_manager.register(create_chat_module(chat_driver))
        module_manager.load(CHAT_MODULE_ID)

        self.ollama_driver = OllamaProviderDriver(
            transport=ollama_transport,
            logger=logger,
            base_url="http://localhost:11434",
        )
        self.ollama_driver.bind_brain(self.brain)

        provider_manager.register(
            create_ollama_provider(
                models=(_test_model(),)  # type: ignore[arg-type]
            ),
            self.ollama_driver,
        )


def _test_model() -> ProviderModel:
    return ProviderModel(
        id="test-model",
        name="test-model",
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
    )


def _provider_request_builder(resolution, model) -> ProviderRequest:  # noqa: ANN001
    return OllamaChatRequest(
        messages=(
            OllamaMessage(role="user", content="Search for parika."),
        ),
        tools=(WEB_SEARCH_TOOL_SPEC,),
    )


def _chat_goal() -> Goal:
    return Goal(
        id="chat-1",
        capability_id=CHAT_CAPABILITY_ID,
        provider_request_builder=_provider_request_builder,
    )


@pytest.fixture
def http_transport() -> _FakeHttpTransport:
    return _FakeHttpTransport()


@pytest.fixture
def ollama_transport() -> _FakeOllamaTransport:
    return _FakeOllamaTransport()


@pytest.fixture
def pipeline(
    ollama_transport: _FakeOllamaTransport,
    http_transport: _FakeHttpTransport,
) -> Pipeline:
    return Pipeline(
        ollama_transport=ollama_transport, http_transport=http_transport
    )


class TestChatWithoutToolCalling:
    def test_direct_answer_flows_through_the_full_pipeline(
        self, pipeline: Pipeline, ollama_transport: _FakeOllamaTransport
    ) -> None:
        ollama_transport.queue_chat_response(
            {
                "message": {"role": "assistant", "content": "Hi there."},
                "done": True,
            }
        )

        response = pipeline.brain.handle(BrainRequest(goals=(_chat_goal(),)))

        assert response.succeeded
        result = response.results[0]
        assert result.status is TaskStatus.COMPLETED
        chat_response = result.response.outputs["result"]
        assert chat_response.message.content == "Hi there."


class TestChatWithToolCalling:
    def test_model_tool_call_reaches_real_web_search_tool(
        self,
        pipeline: Pipeline,
        ollama_transport: _FakeOllamaTransport,
        http_transport: _FakeHttpTransport,
    ) -> None:

        http_transport.queue_response(_search_response())

        ollama_transport.queue_chat_response(
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
        ollama_transport.queue_chat_response(
            {
                "message": {
                    "role": "assistant",
                    "content": "PARIKA is an intelligence kernel.",
                },
                "done": True,
            }
        )

        response = pipeline.brain.handle(BrainRequest(goals=(_chat_goal(),)))

        assert response.succeeded

        chat_response = response.results[0].response.outputs["result"]
        assert chat_response.message.content == (
            "PARIKA is an intelligence kernel."
        )
        assert len(chat_response.tool_invocations) == 1
        assert chat_response.tool_invocations[0].succeeded is True
        # WebSearchToolDriver requests a generous candidate pool
        # (config.DEFAULT_CANDIDATE_POOL_SIZE) from the backend, not
        # just the model's final requested count, so ranking has real
        # headroom before truncation (Issue 6/7).
        assert http_transport.calls == [
            "https://www.google.com/search?q=parika&num=20"
        ]

        tool_messages = [
            message
            for message in ollama_transport.chat_payloads[1]["messages"]
            if message["role"] == "tool"
        ]
        fed_back = json.loads(tool_messages[0]["content"])
        assert fed_back["result"][0]["title"] == "PARIKA Official Site"

    def test_tool_failure_is_fed_back_and_model_still_responds(
        self,
        pipeline: Pipeline,
        ollama_transport: _FakeOllamaTransport,
        http_transport: _FakeHttpTransport,
    ) -> None:

        http_transport.queue_error(WebSearchNetworkError("blocked"))
        http_transport.queue_error(WebSearchNetworkError("blocked"))
        http_transport.queue_error(WebSearchNetworkError("blocked"))

        ollama_transport.queue_chat_response(
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
        ollama_transport.queue_chat_response(
            {
                "message": {
                    "role": "assistant",
                    "content": "I could not search right now.",
                },
                "done": True,
            }
        )

        response = pipeline.brain.handle(BrainRequest(goals=(_chat_goal(),)))

        assert response.succeeded

        chat_response = response.results[0].response.outputs["result"]
        assert chat_response.tool_invocations[0].succeeded is False
        assert chat_response.message.content == (
            "I could not search right now."
        )
