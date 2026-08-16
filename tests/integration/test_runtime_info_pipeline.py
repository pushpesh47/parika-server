"""
End-to-end integration test for the Runtime Info capability, through
the complete real Core stack:

    Planner (Model Selection) -> TaskManager -> CapabilityExecutor ->
    ProviderManager -> Ollama Provider -> (tool calling) -> Brain ->
    Planner -> TaskManager -> CapabilityExecutor -> ToolManager ->
    Runtime Info Tool -> the real system clock

Only the Ollama `OllamaTransport` is faked (deterministic, scripted
responses); every PARIKA component in between - including the real
Runtime Info Tool reading the real system clock - is real. This
mirrors `tests/integration/test_chat_pipeline.py`'s shape for the
Web Search Tool.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
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
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.chat.driver import CHAT_CAPABILITY_ID, ChatModuleDriver
from parika.modules.chat.manifest import CHAT_MODULE_ID, create_chat_module
from parika.modules.runtime_info.driver import RuntimeInfoModuleDriver
from parika.modules.runtime_info.manifest import (
    RUNTIME_INFO_MODULE_ID,
    create_runtime_info_module,
)
from parika.providers.ollama.driver import OllamaProviderDriver
from parika.providers.ollama.manifest import create_ollama_provider
from parika.providers.ollama.messages import OllamaMessage, OllamaToolSpec
from parika.providers.ollama.requests import OllamaChatRequest
from parika.tools.runtime_info.manifest import (
    RUNTIME_INFO_CAPABILITY_ID,
    RUNTIME_INFO_TOOL_AFFORDANCE,
)

RUNTIME_DATETIME_TOOL_SPEC = OllamaToolSpec(
    name=RUNTIME_INFO_TOOL_AFFORDANCE["name"],
    description=RUNTIME_INFO_TOOL_AFFORDANCE["description"],
    capability_id=RUNTIME_INFO_CAPABILITY_ID,
    parameters=RUNTIME_INFO_TOOL_AFFORDANCE["parameters"],
)
"""
Test-local reconstruction of the `runtime.current_datetime` tool spec
from the Runtime Info Tool's own schema (`parika.tools.runtime_info.
manifest.RUNTIME_INFO_TOOL_AFFORDANCE`) -- AI Context Engineering builds
this dynamically at runtime (see `parika.interfaces.ai_context.
tool_context`), so this fixture exists only to give this test's own
`_provider_request_builder` a concrete `tools` tuple to advertise.
"""


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


class _Pipeline:
    def __init__(self, ollama_transport: _FakeOllamaTransport) -> None:
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
            configuration=configuration,
        )
        self.brain = Brain(
            planner=planner, task_manager=self.task_manager, logger=logger
        )

        runtime_info_driver = RuntimeInfoModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
        )
        module_manager.register(
            create_runtime_info_module(runtime_info_driver)
        )
        module_manager.load(RUNTIME_INFO_MODULE_ID)

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
            create_ollama_provider(models=(_test_model(),)),
            self.ollama_driver,
        )


def _test_model() -> ProviderModel:
    return ProviderModel(
        id="test-model",
        name="test-model",
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        execution_features=frozenset({ModelExecutionFeature.TOOL_CALLING}),
    )


def _provider_request_builder(resolution, model) -> ProviderRequest:  # noqa: ANN001
    return OllamaChatRequest(
        messages=(
            OllamaMessage(role="user", content="What time is it in IST?"),
        ),
        tools=(RUNTIME_DATETIME_TOOL_SPEC,),
    )


def _chat_goal() -> Goal:
    return Goal(
        id="chat-1",
        capability_id=CHAT_CAPABILITY_ID,
        inputs={"message": "What time is it in IST?"},
        provider_request_builder=_provider_request_builder,
    )


class TestRuntimeInfoToolCalling:
    def test_model_tool_call_reaches_the_real_system_clock(self) -> None:
        ollama_transport = _FakeOllamaTransport()
        pipeline = _Pipeline(ollama_transport)

        ollama_transport.queue_chat_response(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "get_current_datetime",
                                "arguments": {"timezone": "IST"},
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
                    "content": "It is currently the time reported above, in IST.",
                },
                "done": True,
            }
        )

        response = pipeline.brain.handle(BrainRequest(goals=(_chat_goal(),)))

        assert response.succeeded

        result = response.results[0]
        assert result.status is TaskStatus.COMPLETED

        chat_response = result.response.outputs["result"]
        assert len(chat_response.tool_invocations) == 1

        invocation = chat_response.tool_invocations[0]
        assert invocation.succeeded is True
        assert invocation.capability_id == "runtime.current_datetime"

        tool_result = json.loads(invocation.content)["result"]
        assert tool_result["timezone"] == "Asia/Kolkata"
        assert "date" in tool_result
        assert "time" in tool_result

        tool_messages = [
            message
            for message in ollama_transport.chat_payloads[1]["messages"]
            if message["role"] == "tool"
        ]
        assert len(tool_messages) == 1
        fed_back = json.loads(tool_messages[0]["content"])["result"]
        assert fed_back["timezone"] == "Asia/Kolkata"

    def test_goal_without_execution_requirements_override_still_executes(
        self,
    ) -> None:
        """
        Without an explicit `Goal.metadata["execution_requirements"]`
        override, Planner falls back to the neutral,
        capability-category default (`tool_calling=NOT_NEEDED`) --
        Planner no longer infers requirements from the Goal's message
        text (see `docs/architecture/Request_Understanding.md`). This
        default never hard-excludes a candidate model, so the turn
        still executes exactly as it would for a real Interface turn
        that supplies its own override (see `chat_capability.
        build_chat_goal()`).
        """

        ollama_transport = _FakeOllamaTransport()
        pipeline = _Pipeline(ollama_transport)

        ollama_transport.queue_chat_response(
            {
                "message": {"role": "assistant", "content": "no tool needed"},
                "done": True,
            }
        )

        pipeline.brain.handle(BrainRequest(goals=(_chat_goal(),)))

        sent_payload = ollama_transport.chat_payloads[0]
        # The chat request was still sent - the assertion of interest
        # is that Planner did not raise NoAvailableProviderModelError.
        assert sent_payload["messages"][0]["content"] == (
            "What time is it in IST?"
        )
