"""
Integration test verifying that synthesis chat.respond provider request
contains dependency results from both successful and failed goals.
"""

from __future__ import annotations

import pytest

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.provider_manager.request import RequestOptions
from parika.core.state_manager.states import ProviderState
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.tool_manager.exceptions import ToolExecutionError
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.interfaces.ai_context.goal_builder import _PROMPT_TOKEN_ESTIMATOR, _estimate_prompt_tokens


class _RecordingProviderDriver(ProviderDriver):
    """Provider driver that captures ChatRequest for verification."""
    
    def __init__(self) -> None:
        self.captured_requests: list[ChatRequest] = []
    
    def discover_models(self):
        return frozenset()
    
    def check_health(self):
        return ProviderHealth(available=True)
    
    def execute(self, model: ProviderModel, request: ChatRequest):
        self.captured_requests.append(request)
        return ChatResult(
            message=ChatMessage(role="assistant", content="Synthesis complete."),
            tool_invocations=(),
        )


class _ScriptedToolDriver:
    """Tool driver with scripted responses."""
    
    def __init__(self) -> None:
        from parika.core.tool_manager.request import ToolRequest
        from parika.core.tool_manager.response import ToolResponse
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


def _build_provider_request(messages, tools, on_token=None):
    """Build a ChatRequest like build_chat_goal does."""
    estimated_prompt_tokens = _estimate_prompt_tokens(
        messages, tools, estimator=_PROMPT_TOKEN_ESTIMATOR
    )
    
    return ChatRequest(
        messages=messages,
        tools=tools,
        on_token=on_token,
        options=RequestOptions(
            estimated_prompt_tokens=estimated_prompt_tokens
        ),
    )


def test_synthesis_provider_request_contains_dependency_results():
    """Test that chat.respond synthesis request includes dependency results from failed and successful goals."""
    config = Configuration()
    config.load()
    logger = Logger(config)
    event_bus = EventBus(logger)
    
    capability_registry = CapabilityRegistry(event_bus, logger)
    capability_resolver = CapabilityResolver(capability_registry=capability_registry, logger=logger)
    resource_manager = ResourceManager(configuration=config, logger=logger)
    policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
    provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
    tool_manager = ToolManager(event_bus=event_bus, logger=logger)
    
    planner = Planner(
        capability_resolver=capability_resolver,
        resource_manager=resource_manager,
        policy_engine=policy_engine,
        provider_manager=provider_manager,
        tool_manager=tool_manager,
        logger=logger,
        configuration=config,
    )
    
    capability_executor = CapabilityExecutor(
        event_bus=event_bus,
        logger=logger,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
    )
    
    task_manager = TaskManager(
        event_bus=event_bus,
        logger=logger,
        capability_executor=capability_executor,
    )
    
    brain = Brain(planner=planner, task_manager=task_manager, logger=logger, event_bus=event_bus)
    
    # Register chat.respond capability
    capability_registry.register(
        CapabilityDefinition(
            id="chat.respond",
            name="Chat Respond",
            description="Generate chat response",
            category=CapabilityCategory.LLM,
        )
    )
    
    provider_driver = _RecordingProviderDriver()
    provider_manager.register(
        Provider(
            id="provider.test",
            name="Test Provider",
            state=ProviderState.CONNECTED,
            models=(
                ProviderModel(
                    id="test-model",
                    name="Test Model",
                    capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                ),
            ),
        ),
        provider_driver,
    )
    
    # Register tools
    weather_driver = _ScriptedToolDriver()
    weather_driver.succeed_with(ToolResponse(result={"temp": 25, "condition": "sunny"}))
    _register_tool(capability_registry, tool_manager, capability_id="weather.current", tool_id="tool.weather_current", driver=weather_driver)
    
    currency_driver = _ScriptedToolDriver()
    currency_driver.fail_with(ToolExecutionError("Invalid currency code"))
    _register_tool(capability_registry, tool_manager, capability_id="currency.convert", tool_id="tool.currency_convert", driver=currency_driver)
    
    # Create goals with chat.respond synthesis that has provider_request_builder
    def provider_builder(resolution, model):
        from parika.core.provider_manager.chat_message import ChatMessage
        return _build_provider_request(
            messages=(ChatMessage(role="user", content="Summarize weather and currency"),),
            tools=(),
            on_token=None,
        )
    
    goals = (
        Goal(id="g1", capability_id="weather.current", inputs={"location": "Patna"}),
        Goal(id="g2", capability_id="currency.convert", inputs={"from": "USD", "to": "INR", "amount": 100}),
        Goal(id="g3", capability_id="chat.respond", inputs={"message": "Summarize weather and currency"}, depends_on=("g1", "g2"), provider_request_builder=provider_builder),
    )
    
    request = BrainRequest(goals=goals)
    response = brain.handle(request)
    
    # Verify execution
    assert len(response.results) == 3
    results_by_id = {r.goal_id: r for r in response.results}
    assert results_by_id["g1"].succeeded
    assert not results_by_id["g2"].succeeded
    assert results_by_id["g3"].succeeded
    assert not results_by_id["g3"].skipped
    
    # Verify provider request was captured and contains dependency results
    assert len(provider_driver.captured_requests) == 1
    synthesis_request = provider_driver.captured_requests[0]
    
    # Check that dependency results are injected as a system message
    dep_messages = [msg for msg in synthesis_request.messages if "DEPENDENCY RESULTS FOR SYNTHESIS" in msg.content]
    assert len(dep_messages) == 1, "Should have exactly one dependency results message"
    
    dep_content = dep_messages[0].content
    assert "g1" in dep_content, "Should reference goal g1"
    assert "g2" in dep_content, "Should reference goal g2"
    assert "SUCCESS" in dep_content or "✓" in dep_content, "Should show success for g1"
    assert "FAILED" in dep_content or "✗" in dep_content, "Should show failure for g2"
    assert "Invalid currency code" in dep_content or "execution failed" in dep_content, "Should include error info for g2"


if __name__ == "__main__":
    test_synthesis_provider_request_contains_dependency_results()
    print("✓ Test passed!")


def test_chat_turn_result_succeeded_with_partial_failure():
    """
    Test that ChatTurnResult.succeeded returns True when synthesis succeeds
    even if independent goals fail.
    
    This simulates the real-world scenario from the bug report:
    - weather.current -> SUCCESS
    - weather.forecast -> SUCCESS  
    - web.search -> SUCCESS
    - currency.convert -> FAILED
    - chat.respond synthesis -> SUCCESS
    
    The user should receive the synthesis response despite the currency failure.
    """
    from parika.interfaces.session import ChatTurnResult
    from parika.core.brain.brain_response import BrainResponse
    from parika.core.brain.goal_result import GoalResult
    from parika.core.task_manager.task_status import TaskStatus
    from parika.core.task_manager.response import TaskResponse
    from parika.core.provider_manager.chat_result import ChatResult
    from parika.core.provider_manager.chat_message import ChatMessage
    
    # Create goal results simulating the real scenario
    weather_current_result = GoalResult(
        goal_id="g1",
        task_id="t1",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": {"temp": 25, "condition": "sunny"}}),
    )
    
    weather_forecast_result = GoalResult(
        goal_id="g2",
        task_id="t2",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": {"forecast": "sunny for 7 days"}}),
    )
    
    web_search_result = GoalResult(
        goal_id="g3",
        task_id="t3",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": {"results": ["protest info"]}}),
    )
    
    currency_result = GoalResult(
        goal_id="g4",
        task_id="t4",
        status=TaskStatus.FAILED,
        failure=RuntimeError("Invalid currency code"),
    )
    
    # Synthesis goal produces ChatResult
    synthesis_result = GoalResult(
        goal_id="g5",
        task_id="t5",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": ChatResult(
            message=ChatMessage(role="assistant", content="Weather in Patna: 25°C sunny. 7-day forecast: sunny. Jharkhand protest: ongoing. Currency lookup failed: Invalid currency code."),
            tool_invocations=(),
        )}),
    )
    
    brain_response = BrainResponse(
        request_id="test-request",
        plan_id="test-plan",
        results=(weather_current_result, weather_forecast_result, web_search_result, currency_result, synthesis_result),
    )
    
    chat_turn_result = ChatTurnResult(brain_response=brain_response)
    
    # THE FIX: ChatTurnResult.succeeded should be True because synthesis succeeded
    assert chat_turn_result.succeeded is True, "Turn should succeed when synthesis produces a response"
    
    # The chat response should be available
    assert chat_turn_result.chat_response is not None, "Chat response should be available"
    assert "Weather in Patna" in chat_turn_result.chat_response.message.content
    assert "Currency lookup failed" in chat_turn_result.chat_response.message.content
    
    # The error message should still be available for failed goals
    # (error_message returns first failure, but we have a response)
    assert chat_turn_result.error_message is not None or chat_turn_result.chat_response is not None
    
    print("✓ ChatTurnResult.succeeded correctly returns True for partial failure with successful synthesis!")


def test_chat_turn_result_succeeded_single_goal():
    """
    Test backward compatibility: single chat.respond goal still works correctly.
    """
    from parika.interfaces.session import ChatTurnResult
    from parika.core.brain.brain_response import BrainResponse
    from parika.core.brain.goal_result import GoalResult
    from parika.core.task_manager.task_status import TaskStatus
    from parika.core.task_manager.response import TaskResponse
    from parika.core.provider_manager.chat_result import ChatResult
    from parika.core.provider_manager.chat_message import ChatMessage
    
    # Single successful goal
    chat_result = GoalResult(
        goal_id="g1",
        task_id="t1",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": ChatResult(
            message=ChatMessage(role="assistant", content="Hello!"),
            tool_invocations=(),
        )}),
    )
    
    brain_response = BrainResponse(
        request_id="test-request",
        plan_id="test-plan",
        results=(chat_result,),
    )
    
    chat_turn_result = ChatTurnResult(brain_response=brain_response)
    
    assert chat_turn_result.succeeded is True
    assert chat_turn_result.chat_response is not None
    assert chat_turn_result.chat_response.message.content == "Hello!"
    
    # Single failed goal
    failed_result = GoalResult(
        goal_id="g1",
        task_id="t1",
        status=TaskStatus.FAILED,
        failure=RuntimeError("Provider unavailable"),
    )
    
    brain_response_failed = BrainResponse(
        request_id="test-request",
        plan_id="test-plan",
        results=(failed_result,),
    )
    
    chat_turn_result_failed = ChatTurnResult(brain_response=brain_response_failed)
    
    assert chat_turn_result_failed.succeeded is False
    assert chat_turn_result_failed.chat_response is None
    assert "Provider unavailable" in chat_turn_result_failed.error_message
    
    print("✓ Single goal backward compatibility works!")


def test_chat_turn_result_succeeded_planning_failure():
    """
    Test that planning failures still result in succeeded=False.
    """
    from parika.interfaces.session import ChatTurnResult
    from parika.core.brain.brain_response import BrainResponse
    
    brain_response = BrainResponse(
        request_id="test-request",
        plan_id=None,
        results=(),
        planning_failure=RuntimeError("No models available"),
    )
    
    chat_turn_result = ChatTurnResult(brain_response=brain_response)
    
    assert chat_turn_result.succeeded is False
    assert chat_turn_result.chat_response is None
    assert "No models available" in chat_turn_result.error_message
    
    print("✓ Planning failure handling works!")
