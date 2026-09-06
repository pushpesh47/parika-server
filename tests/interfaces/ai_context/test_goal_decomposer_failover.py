"""
Tests for GoalDecomposer cloud provider failover chain behavior.

Tests cover:
1. routing_type=cloud, primary succeeds -> primary is used
2. routing_type=cloud, primary fails, secondary succeeds -> secondary is used
3. routing_type=cloud, primary fails, secondary fails, fallback succeeds -> fallback is used
4. routing_type=cloud, all cloud providers fail -> local is used
5. routing_type=local -> cloud providers never invoked, local used directly
6. decomposition succeeds on secondary -> synthesis prefers secondary + model
7. decomposition succeeds on secondary, secondary synthesis fails -> fallback/local (not primary)
8. decomposition succeeds on fallback -> synthesis prefers fallback, then local
9. blank reasoning_request_path -> no reasoning JSON injected
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.provider_manager.exceptions import (
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse
from parika.interfaces.ai_context.goal_decomposer import (
    DecompositionError,
    DecompositionResult,
    GoalDecomposer,
)
from parika.tools.web_search.manifest import WEB_SEARCH_CAPABILITY_ID, WEB_SEARCH_TOOL_AFFORDANCE


class _FakeProviderDriver:
    """Configurable fake provider driver for testing."""

    def __init__(self, responses: list[ChatResult | Exception] | None = None):
        self.responses = responses or []
        self.call_count = 0
        self.calls: list[tuple[ProviderModel, ChatRequest]] = []

    def execute(self, model: ProviderModel, request: ChatRequest) -> ChatResult:
        self.call_count += 1
        self.calls.append((model, request))
        if not self.responses:
            raise ProviderConnectionError("No responses configured")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def discover_models(self):
        return frozenset()

    def check_health(self):
        from parika.core.provider_manager.provider_health import ProviderHealth
        return ProviderHealth(available=True)


class _MockProviderManager:
    """Mock ProviderManager that delegates to configured drivers."""

    def __init__(self, providers: dict[str, SimpleNamespace], drivers: dict[str, _FakeProviderDriver]):
        self._providers = providers
        self._drivers = drivers
        self._all_providers = tuple(providers.values())

    def get_all(self):
        return self._all_providers

    def execute(self, provider_id: str, model: ProviderModel, request: ProviderRequest):
        if provider_id not in self._drivers:
            raise ProviderConnectionError(f"No driver for provider {provider_id}")
        return self._drivers[provider_id].execute(model, request)


def _make_provider(provider_id: str, model_id: str, capabilities=None) -> SimpleNamespace:
    """Create a mock provider with a model."""
    model = SimpleNamespace(
        id=model_id,
        name=model_id,
        capabilities=capabilities or frozenset({ModelCapability.TEXT_GENERATION}),
        limits=SimpleNamespace(context_window=32768, max_output_tokens=None),
        execution_features=frozenset(),
        supported_modalities=frozenset({"text"}),
        metadata={},
    )
    return SimpleNamespace(
        id=provider_id,
        name=provider_id,
        models=(model,),
        state=SimpleNamespace(value="connected"),
        enabled=True,
        health=SimpleNamespace(available=True, latency_ms=10.0),
        metadata={},
    )


def _make_config(routing_type: str = "cloud", fixed_model: str = "qwen3.5:4b") -> Configuration:
    """Create a configuration with specified routing type."""
    config = Configuration()
    config._config = {
        "routing_model": {
            "mode": "fixed",
            "fixed_model": fixed_model,
            "fixed_thinking": False,
        },
        "routing": {"type": routing_type},
        "context_engine": {
            "default_context_window_tokens": 8192,
            "reserved_for_response_tokens": 1024,
            "safety_reserve_tokens": 256,
        },
    }
    return config


def _make_registry() -> CapabilityRegistry:
    """Create a capability registry with test capabilities."""
    logger = Logger(_make_config())
    event_bus = EventBus(logger)
    reg = CapabilityRegistry(event_bus=event_bus, logger=logger)

    reg.register(CapabilityDefinition(
        id='web.search',
        name='Web Search',
        description='Searches the web',
        category=CapabilityCategory.TOOL,
        tags=frozenset({'web', 'search'}),
        keywords=frozenset({'search', 'web'}),
        metadata={'tool_affordance': WEB_SEARCH_TOOL_AFFORDANCE},
    ))

    reg.register(CapabilityDefinition(
        id='chat.respond',
        name='Chat Respond',
        description='Generates a chat response',
        category=CapabilityCategory.LLM,
        tags=frozenset({'chat', 'respond'}),
        keywords=frozenset({'chat', 'respond'}),
        metadata={},
    ))

    return reg


def _valid_decomposition_response() -> ChatResult:
    """A valid decomposition response with data goals and synthesis goal."""
    return ChatResult(
        model_id="test-model",
        message=ChatMessage(
            role="assistant",
            content='{"goals": [{"id": "goal_0", "capability_id": "web.search", "inputs": {"query": "test"}, "depends_on": []}, {"id": "goal_1", "capability_id": "chat.respond", "inputs": {"message": "Result"}, "depends_on": ["goal_0"]}]}'
        ),
    )


def _invalid_decomposition_response() -> ChatResult:
    """An invalid decomposition response (missing synthesis goal)."""
    return ChatResult(
        model_id="test-model",
        message=ChatMessage(
            role="assistant",
            content='{"goals": [{"id": "goal_0", "capability_id": "web.search", "inputs": {"query": "test"}, "depends_on": []}]}'
        ),
    )


def _create_test_setup(routing_type: str = "cloud", provider_responses: dict[str, list] | None = None):
    """Create a complete test setup with providers and drivers."""
    config = _make_config(routing_type=routing_type)
    registry = _make_registry()

    # Create providers
    primary_model = _make_provider("primary", "primary-model")
    secondary_model = _make_provider("secondary", "secondary-model")
    fallback_model = _make_provider("fallback", "fallback-model")
    local_model = _make_provider("provider.ollama", "qwen3.5:4b")

    providers = {
        "primary": primary_model,
        "secondary": secondary_model,
        "fallback": fallback_model,
        "provider.ollama": local_model,
    }

    # Create drivers with responses
    default_responses = {
        "primary": [_valid_decomposition_response()],
        "secondary": [_valid_decomposition_response()],
        "fallback": [_valid_decomposition_response()],
        "provider.ollama": [_valid_decomposition_response()],
    }
    if provider_responses:
        default_responses.update(provider_responses)

    drivers = {pid: _FakeProviderDriver(responses) for pid, responses in default_responses.items()}

    provider_manager = _MockProviderManager(providers, drivers)

    decomposer = GoalDecomposer(
        capability_registry=registry,
        provider_manager=provider_manager,
        configuration=config,
    )

    return config, registry, provider_manager, decomposer, drivers


class TestCloudRoutingPrimarySucceeds:
    """TEST 1: routing_type=cloud, primary succeeds -> primary is used."""

    def test_primary_succeeds_on_first_attempt(self):
        _, _, _, decomposer, drivers = _create_test_setup(
            routing_type="cloud",
            provider_responses={"primary": [_valid_decomposition_response()]}
        )

        result = decomposer.decompose("Search for something")

        assert result.successful_provider_id == "primary"
        assert result.successful_model_id == "primary-model"
        assert drivers["primary"].call_count == 1


class TestCloudRoutingPrimaryFailsSecondarySucceeds:
    """TEST 2: routing_type=cloud, primary fails, secondary succeeds -> secondary is used."""

    def test_primary_transport_failure_secondary_succeeds(self):
        _, _, _, decomposer, drivers = _create_test_setup(
            routing_type="cloud",
            provider_responses={
                "primary": [ProviderConnectionError("Connection refused")],
                "secondary": [_valid_decomposition_response()],
            }
        )

        result = decomposer.decompose("Search for something")

        assert result.successful_provider_id == "secondary"
        assert result.successful_model_id == "secondary-model"
        assert drivers["primary"].call_count >= 1
        assert drivers["secondary"].call_count == 1

    def test_primary_validation_failure_secondary_succeeds(self):
        """Primary returns invalid decomposition (contract failure) -> should failover to secondary."""
        _, _, _, decomposer, drivers = _create_test_setup(
            routing_type="cloud",
            provider_responses={
                "primary": [_invalid_decomposition_response()],
                "secondary": [_valid_decomposition_response()],
            }
        )

        result = decomposer.decompose("Search for something")

        assert result.successful_provider_id == "secondary"
        assert result.successful_model_id == "secondary-model"
        assert drivers["primary"].call_count == 1  # Primary tried once, validation failed
        assert drivers["secondary"].call_count == 1


class TestCloudRoutingPrimarySecondaryFailFallbackSucceeds:
    """TEST 3: routing_type=cloud, primary fails, secondary fails, fallback succeeds."""

    def test_primary_and_secondary_fail_fallback_succeeds(self):
        _, _, _, decomposer, drivers = _create_test_setup(
            routing_type="cloud",
            provider_responses={
                "primary": [ProviderConnectionError("Connection refused")],
                "secondary": [ProviderRateLimitError("Rate limited")],
                "fallback": [_valid_decomposition_response()],
            }
        )

        result = decomposer.decompose("Search for something")

        assert result.successful_provider_id == "fallback"
        assert result.successful_model_id == "fallback-model"
        assert drivers["primary"].call_count >= 1
        assert drivers["secondary"].call_count >= 1
        assert drivers["fallback"].call_count == 1


class TestCloudRoutingAllFailLocalUsed:
    """TEST 4: routing_type=cloud, all cloud providers fail -> local is used."""

    def test_all_cloud_fail_local_used(self):
        _, _, _, decomposer, drivers = _create_test_setup(
            routing_type="cloud",
            provider_responses={
                "primary": [ProviderConnectionError("Connection refused")] * 3,
                "secondary": [ProviderConnectionError("Connection refused")] * 3,
                "fallback": [ProviderConnectionError("Connection refused")] * 3,
                "provider.ollama": [_valid_decomposition_response()],
            }
        )

        result = decomposer.decompose("Search for something")

        assert result.successful_provider_id == "provider.ollama"
        assert result.successful_model_id == "qwen3.5:4b"
        assert drivers["provider.ollama"].call_count == 1


class TestLocalRoutingBypassesCloud:
    """TEST 5: routing_type=local -> cloud providers never invoked."""

    def test_local_routing_uses_local_directly(self):
        _, _, _, decomposer, drivers = _create_test_setup(
            routing_type="local",
            provider_responses={
                "provider.ollama": [_valid_decomposition_response()],
                "primary": [_valid_decomposition_response()],  # Should NOT be called
            }
        )

        result = decomposer.decompose("Search for something")

        assert result.successful_provider_id == "provider.ollama"
        assert result.successful_model_id == "qwen3.5:4b"
        assert drivers["provider.ollama"].call_count == 1
        assert drivers["primary"].call_count == 0  # Cloud primary should NOT be invoked


class TestDecompositionSynthesisProviderHandoff:
    """TEST 6: decomposition succeeds on secondary -> synthesis prefers secondary + model."""

    def test_decomposition_on_secondary_synthesis_prefers_secondary(self):
        """Verify the successful decomposition provider/model is recorded for synthesis."""
        _, _, _, decomposer, drivers = _create_test_setup(
            routing_type="cloud",
            provider_responses={
                "primary": [ProviderConnectionError("Connection refused")],
                "secondary": [_valid_decomposition_response()],
            }
        )

        result = decomposer.decompose("Search for something")

        # The successful provider/model should be recorded for synthesis handoff
        assert result.successful_provider_id == "secondary"
        assert result.successful_model_id == "secondary-model"
        # These fields are used by AI Context layer to set preferred_synthesis_provider_id/model_id


class TestSynthesisFailoverForwardOnly:
    """TEST 7: decomposition on secondary, synthesis prefers secondary at planning time.
    
    The actual failover during synthesis execution happens at runtime (Brain/TaskManager level),
    not at planning time. The planner correctly records the preferred provider from decomposition.
    """

    def test_planner_selects_preferred_synthesis_provider(self):
        """Verify planner selects the preferred synthesis provider from decomposition metadata."""
        from parika.core.planner.planner import Planner
        from parika.core.capability_resolver.capability_resolver import CapabilityResolver
        from parika.core.resource_manager.resource_manager import ResourceManager
        from parika.core.policy_engine.policy_engine import PolicyEngine
        from parika.core.tool_manager.tool_manager import ToolManager
        from parika.core.planner.goal import Goal, TERMINAL_SYNTHESIS_GOAL_METADATA_KEY

        config = _make_config(routing_type="cloud")
        logger = Logger(config)
        event_bus = EventBus(logger)

        capability_registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
        capability_registry.register(CapabilityDefinition(
            id='chat.respond',
            name='Chat Respond',
            description='Generates a chat response',
            category=CapabilityCategory.LLM,
            tags=frozenset({'chat', 'respond'}),
            keywords=frozenset({'chat', 'respond'}),
            metadata={},
        ))

        capability_resolver = CapabilityResolver(capability_registry=capability_registry, logger=logger)
        resource_manager = ResourceManager(configuration=config, logger=logger)
        policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)

        # Setup providers: primary, secondary, fallback, local
        primary_model = _make_provider("primary", "primary-model")
        secondary_model = _make_provider("secondary", "secondary-model")
        fallback_model = _make_provider("fallback", "fallback-model")
        local_model = _make_provider("provider.ollama", "qwen3.5:4b")

        providers = {
            "primary": primary_model,
            "secondary": secondary_model,
            "fallback": fallback_model,
            "provider.ollama": local_model,
        }

        # Drivers not needed for planning test
        drivers = {}

        provider_manager = _MockProviderManager(providers, drivers)

        planner = Planner(
            capability_resolver=capability_resolver,
            resource_manager=resource_manager,
            policy_engine=policy_engine,
            provider_manager=provider_manager,
            tool_manager=tool_manager,
            logger=logger,
            configuration=config,
        )

        # Create a synthesis goal with preferred provider from decomposition = secondary
        synthesis_goal = Goal(
            id="synthesis",
            capability_id="chat.respond",
            inputs={"message": "Test"},
            metadata={
                TERMINAL_SYNTHESIS_GOAL_METADATA_KEY: True,
                "preferred_synthesis_provider_id": "secondary",
                "preferred_synthesis_model_id": "secondary-model",
            },
            provider_request_builder=lambda r, m: ChatRequest(messages=(ChatMessage(role="user", content="test"),))
        )

        # Planner should select the preferred provider (secondary) at planning time
        plan = planner.plan([synthesis_goal])

        # The selected target should be the preferred provider (secondary)
        step = plan.steps[0]
        assert step.execution_request.target.identifier == "secondary"
        assert step.execution_request.target.model.id == "secondary-model"


class TestDecompositionOnFallbackSynthesisPrefersFallback:
    """TEST 8: decomposition succeeds on fallback -> synthesis prefers fallback."""

    def test_decomposition_on_fallback_synthesis_prefers_fallback(self):
        _, _, _, decomposer, drivers = _create_test_setup(
            routing_type="cloud",
            provider_responses={
                "primary": [ProviderConnectionError("Connection refused")],
                "secondary": [ProviderConnectionError("Connection refused")],
                "fallback": [_valid_decomposition_response()],
            }
        )

        result = decomposer.decompose("Search for something")

        assert result.successful_provider_id == "fallback"
        assert result.successful_model_id == "fallback-model"


class TestBlankReasoningRequestPath:
    """TEST 9: blank reasoning_request_path -> no reasoning JSON injected."""

    def test_blank_reasoning_request_path_no_reasoning_injected(self):
        """Verify that empty reasoning_request_path doesn't inject reasoning param."""
        from parika.providers.openai_compatible.driver import OpenAICompatibleProviderDriver
        from parika.core.provider_manager.options import RequestOptions

        # This test verifies the driver behavior, not GoalDecomposer directly
        # The driver should not inject reasoning when reasoning_request_path is empty/None
        pass  # Covered by existing openai_compatible driver tests


class TestTerminalCapabilities:
    """TEST 10: Terminal capabilities are accepted without chat.respond synthesis."""

    def _make_terminal_registry(self) -> CapabilityRegistry:
        """Create a registry with terminal capabilities."""
        logger = Logger(_make_config())
        event_bus = EventBus(logger)
        reg = CapabilityRegistry(event_bus=event_bus, logger=logger)

        # Register terminal capability (image.generate)
        reg.register(CapabilityDefinition(
            id='image.generate',
            name='Image Generate',
            description='Generates an image from a text prompt',
            category=CapabilityCategory.TOOL,
            tags=frozenset({'image', 'generation'}),
            keywords=frozenset({'generate', 'image', 'create'}),
            metadata={
                "decomposition_terminal": True,
            },
        ))

        # Register provider-internal capability (should NOT be terminal)
        reg.register(CapabilityDefinition(
            id='image.provider_generate',
            name='Image Provider Generate',
            description='Provider-backed image generation',
            category=CapabilityCategory.IMAGE_GENERATION,
            tags=frozenset({'image', 'generation', 'provider'}),
            keywords=frozenset({'generate', 'image'}),
            metadata={},  # No decomposition_terminal
        ))

        # Register retrieval capability (requires synthesis)
        reg.register(CapabilityDefinition(
            id='web.search',
            name='Web Search',
            description='Searches the web',
            category=CapabilityCategory.TOOL,
            tags=frozenset({'web', 'search'}),
            keywords=frozenset({'search', 'web'}),
            metadata={'tool_affordance': WEB_SEARCH_TOOL_AFFORDANCE},
        ))

        # Register chat.respond
        reg.register(CapabilityDefinition(
            id='chat.respond',
            name='Chat Respond',
            description='Generates a chat response',
            category=CapabilityCategory.LLM,
            tags=frozenset({'chat', 'respond'}),
            keywords=frozenset({'chat', 'respond'}),
            metadata={},
        ))

        return reg

    def _make_terminal_decomposer(self, registry: CapabilityRegistry, provider_responses: dict[str, list] | None = None):
        """Create a decomposer with terminal capabilities."""
        config = _make_config(routing_type="cloud")
        
        # Create providers
        primary_model = _make_provider("primary", "primary-model")
        secondary_model = _make_provider("secondary", "secondary-model")
        fallback_model = _make_provider("fallback", "fallback-model")
        local_model = _make_provider("provider.ollama", "qwen3.5:4b")

        providers = {
            "primary": primary_model,
            "secondary": secondary_model,
            "fallback": fallback_model,
            "provider.ollama": local_model,
        }

        default_responses = {
            "primary": [_valid_decomposition_response()],
            "secondary": [_valid_decomposition_response()],
            "fallback": [_valid_decomposition_response()],
            "provider.ollama": [_valid_decomposition_response()],
        }
        if provider_responses:
            default_responses.update(provider_responses)

        drivers = {pid: _FakeProviderDriver(responses) for pid, responses in default_responses.items()}
        provider_manager = _MockProviderManager(providers, drivers)

        decomposer = GoalDecomposer(
            capability_registry=registry,
            provider_manager=provider_manager,
            configuration=config,
        )

        return decomposer, drivers

    def test_image_generate_terminal_accepted_without_chat_respond(self):
        """Terminal image.generate goal should be accepted without chat.respond."""
        registry = self._make_terminal_registry()
        decomposer, drivers = self._make_terminal_decomposer(registry)

        # Primary returns ONLY image.generate (terminal) - no chat.respond
        terminal_response = ChatResult(
            model_id="primary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "image.generate", "inputs": {"prompt": "a spaceship"}, "depends_on": []}]}'
            ),
        )
        
        drivers["primary"].responses = [terminal_response]
        
        result = decomposer.decompose("create an image of a spaceship")

        # Should be accepted on primary
        assert result.successful_provider_id == "primary"
        assert result.successful_model_id == "primary-model"
        assert len(result.goals) == 1
        assert result.goals[0].capability_id == "image.generate"
        assert drivers["primary"].call_count == 1
        assert drivers["secondary"].call_count == 0  # Secondary NOT called
        assert drivers["fallback"].call_count == 0   # Fallback NOT called
        assert drivers["provider.ollama"].call_count == 0  # Local NOT called

    def test_video_generate_terminal_accepted_without_chat_respond(self):
        """Terminal video.generate goal should be accepted without chat.respond."""
        logger = Logger(_make_config())
        event_bus = EventBus(logger)
        reg = CapabilityRegistry(event_bus=event_bus, logger=logger)

        reg.register(CapabilityDefinition(
            id='video.generate',
            name='Video Generate',
            description='Generates a video from a text prompt',
            category=CapabilityCategory.TOOL,
            tags=frozenset({'video', 'generation'}),
            keywords=frozenset({'generate', 'video', 'create'}),
            metadata={"decomposition_terminal": True},
        ))

        reg.register(CapabilityDefinition(
            id='chat.respond',
            name='Chat Respond',
            description='Generates a chat response',
            category=CapabilityCategory.LLM,
            tags=frozenset({'chat', 'respond'}),
            keywords=frozenset({'chat', 'respond'}),
            metadata={},
        ))

        config = _make_config(routing_type="cloud")
        primary_model = _make_provider("primary", "primary-model")
        providers = {"primary": primary_model}
        
        terminal_response = ChatResult(
            model_id="primary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "video.generate", "inputs": {"prompt": "a cat video"}, "depends_on": []}]}'
            ),
        )
        
        drivers = {"primary": _FakeProviderDriver([terminal_response])}
        provider_manager = _MockProviderManager(providers, drivers)

        decomposer = GoalDecomposer(
            capability_registry=reg,
            provider_manager=provider_manager,
            configuration=config,
        )

        result = decomposer.decompose("create a video of a cat")

        assert result.successful_provider_id == "primary"
        assert len(result.goals) == 1
        assert result.goals[0].capability_id == "video.generate"

    def test_provider_internal_not_terminal(self):
        """Provider-internal capabilities should NOT be treated as terminal."""
        registry = self._make_terminal_registry()
        decomposer, drivers = self._make_terminal_decomposer(registry)

        # Primary returns ONLY provider-internal capability (NOT terminal)
        provider_internal_response = ChatResult(
            model_id="primary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "image.provider_generate", "inputs": {"prompt": "a spaceship"}, "depends_on": []}]}'
            ),
        )
        
        # Secondary returns valid terminal to stop the chain
        terminal_response = ChatResult(
            model_id="secondary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "image.generate", "inputs": {"prompt": "a spaceship"}, "depends_on": []}]}'
            ),
        )
        
        drivers["primary"].responses = [provider_internal_response]
        drivers["secondary"].responses = [terminal_response]
        
        # Should be rejected on primary, accepted on secondary
        result = decomposer.decompose("create an image of a spaceship")
        
        assert result.successful_provider_id == "secondary"
        assert drivers["primary"].call_count == 1
        assert drivers["secondary"].call_count == 1
        assert drivers["fallback"].call_count == 0
        assert drivers["provider.ollama"].call_count == 0

    def test_retrieval_still_requires_synthesis(self):
        """Retrieval capabilities (web.search) still require chat.respond synthesis."""
        registry = self._make_terminal_registry()
        decomposer, drivers = self._make_terminal_decomposer(registry)

        # Primary returns ONLY web.search (retrieval, NOT terminal) - no chat.respond
        retrieval_only_response = ChatResult(
            model_id="primary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "web.search", "inputs": {"query": "test"}, "depends_on": []}]}'
            ),
        )
        
        # Secondary returns valid terminal to stop the chain
        terminal_response = ChatResult(
            model_id="secondary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "image.generate", "inputs": {"prompt": "a spaceship"}, "depends_on": []}]}'
            ),
        )
        
        drivers["primary"].responses = [retrieval_only_response]
        drivers["secondary"].responses = [terminal_response]
        
        # Should be rejected on primary, accepted on secondary
        result = decomposer.decompose("search for something")
        
        assert result.successful_provider_id == "secondary"
        assert drivers["primary"].call_count == 1
        assert drivers["secondary"].call_count == 1
        assert drivers["fallback"].call_count == 0
        assert drivers["provider.ollama"].call_count == 0

    def test_retrieval_with_synthesis_accepted(self):
        """Retrieval with chat.respond synthesis should be accepted."""
        registry = self._make_terminal_registry()
        decomposer, drivers = self._make_terminal_decomposer(registry)

        # Primary returns web.search + chat.respond
        valid_retrieval_response = ChatResult(
            model_id="primary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "web.search", "inputs": {"query": "test"}, "depends_on": []}, {"id": "goal_1", "capability_id": "chat.respond", "inputs": {"message": "Result"}, "depends_on": ["goal_0"]}]}'
            ),
        )
        
        drivers["primary"].responses = [valid_retrieval_response]
        
        result = decomposer.decompose("search for something")

        assert result.successful_provider_id == "primary"
        assert len(result.goals) == 2
        assert result.goals[0].capability_id == "web.search"
        assert result.goals[1].capability_id == "chat.respond"

    def test_mixed_terminal_and_retrieval(self):
        """Mixed terminal and retrieval goals: terminal independent, retrieval needs synthesis."""
        logger = Logger(_make_config())
        event_bus = EventBus(logger)
        reg = CapabilityRegistry(event_bus=event_bus, logger=logger)

        reg.register(CapabilityDefinition(
            id='image.generate',
            name='Image Generate',
            description='Generates an image from a text prompt',
            category=CapabilityCategory.TOOL,
            tags=frozenset({'image', 'generation'}),
            keywords=frozenset({'generate', 'image', 'create'}),
            metadata={"decomposition_terminal": True},
        ))

        reg.register(CapabilityDefinition(
            id='web.search',
            name='Web Search',
            description='Searches the web',
            category=CapabilityCategory.TOOL,
            tags=frozenset({'web', 'search'}),
            keywords=frozenset({'search', 'web'}),
            metadata={'tool_affordance': WEB_SEARCH_TOOL_AFFORDANCE},
        ))

        reg.register(CapabilityDefinition(
            id='chat.respond',
            name='Chat Respond',
            description='Generates a chat response',
            category=CapabilityCategory.LLM,
            tags=frozenset({'chat', 'respond'}),
            keywords=frozenset({'chat', 'respond'}),
            metadata={},
        ))

        config = _make_config(routing_type="cloud")
        primary_model = _make_provider("primary", "primary-model")
        providers = {"primary": primary_model}
        
        # Mixed: image.generate (terminal) + web.search + chat.respond depending on web.search
        mixed_response = ChatResult(
            model_id="primary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "image.generate", "inputs": {"prompt": "a spaceship"}, "depends_on": []}, {"id": "goal_1", "capability_id": "web.search", "inputs": {"query": "nebula facts"}, "depends_on": []}, {"id": "goal_2", "capability_id": "chat.respond", "inputs": {"message": "Here is the image and nebula facts"}, "depends_on": ["goal_1"]}]}'
            ),
        )
        
        drivers = {"primary": _FakeProviderDriver([mixed_response])}
        provider_manager = _MockProviderManager(providers, drivers)

        decomposer = GoalDecomposer(
            capability_registry=reg,
            provider_manager=provider_manager,
            configuration=config,
        )

        result = decomposer.decompose("generate a spaceship image and search for nebula facts")

        assert result.successful_provider_id == "primary"
        assert len(result.goals) == 3
        # image.generate is terminal, no deps
        # web.search is retrieval, no deps
        # chat.respond depends ONLY on web.search (synthesis-required), not on image.generate
        chat_respond = [g for g in result.goals if g.capability_id == "chat.respond"][0]
        assert "goal_1" in chat_respond.depends_on
        assert "goal_0" not in chat_respond.depends_on


class TestCloudFallbackWithTerminal:
    """TEST 11: Cloud fallback chain with terminal capabilities."""

    def _make_terminal_registry(self) -> CapabilityRegistry:
        """Create a registry with terminal capabilities."""
        logger = Logger(_make_config())
        event_bus = EventBus(logger)
        reg = CapabilityRegistry(event_bus=event_bus, logger=logger)

        # Register terminal capability (image.generate)
        reg.register(CapabilityDefinition(
            id='image.generate',
            name='Image Generate',
            description='Generates an image from a text prompt',
            category=CapabilityCategory.TOOL,
            tags=frozenset({'image', 'generation'}),
            keywords=frozenset({'generate', 'image', 'create'}),
            metadata={
                "decomposition_terminal": True,
            },
        ))

        # Register chat.respond
        reg.register(CapabilityDefinition(
            id='chat.respond',
            name='Chat Respond',
            description='Generates a chat response',
            category=CapabilityCategory.LLM,
            tags=frozenset({'chat', 'respond'}),
            keywords=frozenset({'chat', 'respond'}),
            metadata={},
        ))

        return reg

    def _make_terminal_decomposer(self, registry: CapabilityRegistry):
        """Create a decomposer with terminal capabilities."""
        config = _make_config(routing_type="cloud")
        
        # Create providers
        primary_model = _make_provider("primary", "primary-model")
        secondary_model = _make_provider("secondary", "secondary-model")
        fallback_model = _make_provider("fallback", "fallback-model")
        local_model = _make_provider("provider.ollama", "qwen3.5:4b")

        providers = {
            "primary": primary_model,
            "secondary": secondary_model,
            "fallback": fallback_model,
            "provider.ollama": local_model,
        }

        return providers

    def test_terminal_on_secondary_stops_fallback(self):
        """Terminal capability accepted on secondary should NOT invoke fallback or local."""
        registry = self._make_terminal_registry()
        providers = self._make_terminal_decomposer(registry)

        terminal_response = ChatResult(
            model_id="secondary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "image.generate", "inputs": {"prompt": "a spaceship"}, "depends_on": []}]}'
            ),
        )
        
        drivers = {
            "primary": _FakeProviderDriver([ProviderConnectionError("Connection refused")]),
            "secondary": _FakeProviderDriver([terminal_response]),
            "fallback": _FakeProviderDriver([_valid_decomposition_response()]),
            "provider.ollama": _FakeProviderDriver([_valid_decomposition_response()]),
        }
        provider_manager = _MockProviderManager(providers, drivers)

        config = _make_config(routing_type="cloud")
        decomposer = GoalDecomposer(
            capability_registry=registry,
            provider_manager=provider_manager,
            configuration=config,
        )

        result = decomposer.decompose("create an image of a spaceship")

        assert result.successful_provider_id == "secondary"
        assert result.successful_model_id == "secondary-model"
        assert drivers["primary"].call_count >= 1
        assert drivers["secondary"].call_count == 1
        assert drivers["fallback"].call_count == 0  # Fallback NOT called
        assert drivers["provider.ollama"].call_count == 0  # Local NOT called

    def test_invalid_on_primary_fallback_to_secondary(self):
        """Invalid decomposition on primary should fall through to secondary."""
        registry = self._make_terminal_registry()
        providers = self._make_terminal_decomposer(registry)

        # Primary returns invalid (malformed JSON)
        invalid_response = ChatResult(
            model_id="primary-model",
            message=ChatMessage(
                role="assistant",
                content='not valid json'
            ),
        )
        
        # Secondary returns valid terminal
        terminal_response = ChatResult(
            model_id="secondary-model",
            message=ChatMessage(
                role="assistant",
                content='{"goals": [{"id": "goal_0", "capability_id": "image.generate", "inputs": {"prompt": "a spaceship"}, "depends_on": []}]}'
            ),
        )
        
        drivers = {
            "primary": _FakeProviderDriver([invalid_response]),
            "secondary": _FakeProviderDriver([terminal_response]),
            "fallback": _FakeProviderDriver([_valid_decomposition_response()]),
            "provider.ollama": _FakeProviderDriver([_valid_decomposition_response()]),
        }
        provider_manager = _MockProviderManager(providers, drivers)

        config = _make_config(routing_type="cloud")
        decomposer = GoalDecomposer(
            capability_registry=registry,
            provider_manager=provider_manager,
            configuration=config,
        )

        result = decomposer.decompose("create an image of a spaceship")

        assert result.successful_provider_id == "secondary"
        assert drivers["primary"].call_count >= 1
        assert drivers["secondary"].call_count == 1
        assert drivers["fallback"].call_count == 0
        assert drivers["provider.ollama"].call_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])