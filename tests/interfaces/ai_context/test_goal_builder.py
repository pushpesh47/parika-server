"""
Unit tests for `parika.interfaces.ai_context.goal_builder`, focused on
the Worker Model Inventory self-exclusion wiring (see
`worker_inventory.py` for the rendering itself, tested separately) and
the Runtime Context Budget's `estimated_prompt_tokens` measurement
(the num_ctx fix).
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.tool_spec import ToolSpec
from parika.interfaces.ai_context.goal_builder import build_chat_goal


class _NullDriver:
    def discover_models(self):
        return ()

    def check_health(self):
        raise NotImplementedError

    def execute(self, *, model, request):
        raise NotImplementedError


def _provider_manager(*providers: Provider) -> ProviderManager:
    logger = Logger(Configuration())
    manager = ProviderManager(EventBus(logger), logger)

    for provider in providers:
        # `ProviderManager.register()` stores the supplied `Provider`
        # object as-is, so a `Provider` already carrying `models` can
        # be registered directly with no separate discovery round
        # trip.
        manager.register(provider, _NullDriver())

    return manager


class TestBuildChatGoalWorkerInventoryInjection:
    def test_no_provider_manager_leaves_messages_unchanged(self) -> None:
        messages = (ChatMessage(role="user", content="hi"),)
        goal = build_chat_goal(messages=messages, tools=(), on_token=None)

        request = goal.provider_request_builder(None, None)  # type: ignore[arg-type]

        assert request.messages == messages

    def test_injects_inventory_before_final_message_when_manager_supplied(
        self,
    ) -> None:
        routing_model = ProviderModel(id="qwen3.6", name="qwen3.6")
        worker_model = ProviderModel(id="minicpm-v4.5", name="minicpm-v4.5")
        provider = Provider(
            id="provider.ollama",
            name="provider.ollama",
            models=(routing_model, worker_model),  # type: ignore[arg-type]
        )
        manager = _provider_manager(provider)

        messages = (
            ChatMessage(role="system", content="system prompt"),
            ChatMessage(role="user", content="hi"),
        )
        goal = build_chat_goal(
            messages=messages, tools=(), on_token=None, provider_manager=manager
        )

        request = goal.provider_request_builder(None, routing_model)  # type: ignore[arg-type]

        assert len(request.messages) == 3
        assert request.messages[0] == messages[0]
        assert request.messages[-1] == messages[-1]
        inventory_message = request.messages[1]
        assert inventory_message.role == "system"
        assert "minicpm-v4.5" in inventory_message.content

    def test_excludes_exactly_the_model_planner_selected(self) -> None:
        routing_model = ProviderModel(id="qwen3.6", name="qwen3.6")
        worker_model = ProviderModel(id="minicpm-v4.5", name="minicpm-v4.5")
        provider = Provider(
            id="provider.ollama",
            name="provider.ollama",
            models=(routing_model, worker_model),  # type: ignore[arg-type]
        )
        manager = _provider_manager(provider)

        messages = (ChatMessage(role="user", content="hi"),)
        goal = build_chat_goal(
            messages=messages, tools=(), on_token=None, provider_manager=manager
        )

        # Planner selects `routing_model` for *this* Goal -- the
        # closure receives it as `model`, exactly as
        # `Planner._select_provider_model()` does at planner.py:676.
        request = goal.provider_request_builder(None, routing_model)  # type: ignore[arg-type]

        inventory_message = request.messages[0]
        assert "minicpm-v4.5" in inventory_message.content
        assert "qwen3.6" not in inventory_message.content

    def test_no_inventory_message_when_no_other_models_exist(self) -> None:
        routing_model = ProviderModel(id="qwen3.6", name="qwen3.6")
        provider = Provider(
            id="provider.ollama",
            name="provider.ollama",
            models=(routing_model,),  # type: ignore[arg-type]
        )
        manager = _provider_manager(provider)

        messages = (ChatMessage(role="user", content="hi"),)
        goal = build_chat_goal(
            messages=messages, tools=(), on_token=None, provider_manager=manager
        )

        request = goal.provider_request_builder(None, routing_model)  # type: ignore[arg-type]

        assert request.messages == messages

    def test_different_selected_model_excludes_that_one_instead(self) -> None:
        model_a = ProviderModel(id="model-a", name="model-a")
        model_b = ProviderModel(id="model-b", name="model-b")
        provider = Provider(
            id="provider.ollama",
            name="provider.ollama",
            models=(model_a, model_b),  # type: ignore[arg-type]
        )
        manager = _provider_manager(provider)

        messages = (ChatMessage(role="user", content="hi"),)
        goal = build_chat_goal(
            messages=messages, tools=(), on_token=None, provider_manager=manager
        )

        request_excluding_a = goal.provider_request_builder(None, model_a)  # type: ignore[arg-type]
        request_excluding_b = goal.provider_request_builder(None, model_b)  # type: ignore[arg-type]

        assert "model-a" not in request_excluding_a.messages[0].content
        assert "model-b" in request_excluding_a.messages[0].content
        assert "model-b" not in request_excluding_b.messages[0].content
        assert "model-a" in request_excluding_b.messages[0].content


class TestBuildChatGoalPromptTokenEstimation:
    """
    Coverage for the Runtime Context Budget's `required_prompt_tokens`
    input: AI Context Engineering's Prompt Engineering responsibility
    measures the complete, already-assembled prompt -- including
    Worker Inventory, spliced in just above this measurement -- and
    carries the result on the built `ChatRequest`'s
    `options.estimated_prompt_tokens` field, exactly once, without
    summing named parts individually.
    """

    def test_estimate_is_set_on_the_built_request(self) -> None:
        messages = (
            ChatMessage(role="system", content="You are PARIKA."),
            ChatMessage(role="user", content="hi"),
        )
        goal = build_chat_goal(messages=messages, tools=(), on_token=None)

        request = goal.provider_request_builder(None, None)  # type: ignore[arg-type]

        assert isinstance(request.options.estimated_prompt_tokens, int)
        assert request.options.estimated_prompt_tokens > 0

    def test_larger_message_content_increases_the_estimate(self) -> None:
        short_goal = build_chat_goal(
            messages=(ChatMessage(role="user", content="hi"),),
            tools=(),
            on_token=None,
        )
        long_goal = build_chat_goal(
            messages=(
                ChatMessage(role="user", content="hi " * 500),
            ),
            tools=(),
            on_token=None,
        )

        short_request = short_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        long_request = long_goal.provider_request_builder(None, None)  # type: ignore[arg-type]

        assert (
            long_request.options.estimated_prompt_tokens
            > short_request.options.estimated_prompt_tokens
        )

    def test_tool_descriptions_increase_the_estimate(self) -> None:
        messages = (ChatMessage(role="user", content="hi"),)
        tool = ToolSpec(
            name="some_tool",
            description="A tool with a reasonably long description "
            "so its contribution to the estimate is unambiguous.",
            parameters={"type": "object", "properties": {}},
        )

        without_tools = build_chat_goal(messages=messages, tools=(), on_token=None)
        with_tools = build_chat_goal(messages=messages, tools=(tool,), on_token=None)

        request_without_tools = without_tools.provider_request_builder(None, None)  # type: ignore[arg-type]
        request_with_tools = with_tools.provider_request_builder(None, None)  # type: ignore[arg-type]

        assert (
            request_with_tools.options.estimated_prompt_tokens
            > request_without_tools.options.estimated_prompt_tokens
        )

    def test_worker_inventory_participates_in_the_estimate(self) -> None:
        """
        The estimate is taken from the one, final, complete assembly
        -- after Worker Inventory has already been spliced in -- so
        it automatically reflects that content with no separate
        estimation step of its own.
        """

        routing_model = ProviderModel(id="qwen3.6", name="qwen3.6")
        worker_model = ProviderModel(
            id="minicpm-v4.5",
            name="minicpm-v4.5",
            description="A vision-capable worker model with a "
            "reasonably long description.",
        )
        provider = Provider(
            id="provider.ollama",
            name="provider.ollama",
            models=(routing_model, worker_model),  # type: ignore[arg-type]
        )
        manager = _provider_manager(provider)

        messages = (ChatMessage(role="user", content="hi"),)

        without_manager = build_chat_goal(
            messages=messages, tools=(), on_token=None
        )
        with_manager = build_chat_goal(
            messages=messages, tools=(), on_token=None, provider_manager=manager
        )

        request_without_manager = without_manager.provider_request_builder(
            None, routing_model  # type: ignore[arg-type]
        )
        request_with_manager = with_manager.provider_request_builder(
            None, routing_model  # type: ignore[arg-type]
        )

        assert (
            request_with_manager.options.estimated_prompt_tokens
            > request_without_manager.options.estimated_prompt_tokens
        )
