"""
Unit tests for `parika.interfaces.chat_capability` -- the thin
orchestration layer over `parika.interfaces.ai_context`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.tool_spec import ToolSpec
from parika.interfaces.chat_capability import (
    build_assistant_system_prompt,
    build_chat_goal,
    discover_tool_specs,
)
from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.modules.chat.driver import CHAT_CAPABILITY_ID
from parika.tools.memory.manifest import (
    MEMORY_CAPABILITY_REMEMBER,
    MEMORY_TOOL_AFFORDANCES,
)
from parika.tools.web_search.manifest import (
    WEB_SEARCH_CAPABILITY_ID,
    WEB_SEARCH_TOOL_AFFORDANCE,
)

# Test-local reconstructions of well-known tool specs from each Tool's
# own schema -- AI Context Engineering builds these dynamically at
# runtime (see `parika.interfaces.ai_context.tool_context`); these
# constants exist only so tests have a concrete `ToolSpec` to assert
# against or pass as fixture data.
WEB_SEARCH_TOOL_SPEC = ToolSpec(
    name="web_search",
    description=WEB_SEARCH_TOOL_AFFORDANCE["description"],
    capability_id=WEB_SEARCH_CAPABILITY_ID,
    parameters=WEB_SEARCH_TOOL_AFFORDANCE["parameters"],
)

_MEMORY_REMEMBER_AFFORDANCE = MEMORY_TOOL_AFFORDANCES[MEMORY_CAPABILITY_REMEMBER]


class _NullOllamaTransport:
    def request_json(
        self, method: str, url: str, *, payload, timeout
    ) -> dict[str, Any]:
        return {}

    def stream_lines(
        self, method: str, url: str, *, payload, timeout
    ) -> Iterator[dict[str, Any]]:
        return iter(())


@pytest.fixture
def runtime(tmp_path):
    runtime = build_default_runtime(
        ollama_transport=_NullOllamaTransport(),
        discover_ollama_models=False,
        discover_comfyui_models=False,
        data_directory=tmp_path / "data",
    )
    yield runtime
    shutdown_runtime(runtime)


class TestDiscoverToolSpecs:
    """
    `chat_capability.discover_tool_specs()` orchestrates Automatic
    Capability Discovery (`ai_context.capability_context`) and Tool
    Context construction plus the two fixed-scope memory-authorization
    gates (`ai_context.tool_context`) -- no domain/keyword routing
    survives (see `docs/architecture/Request_Understanding.md`).
    """

    def test_includes_web_search_with_its_own_affordance_contract(
        self, runtime
    ) -> None:
        # "search the web for news" contains tokens that match web.search capability
        specs = discover_tool_specs(runtime, text="search the web for news")
        by_capability = {spec.capability_id: spec for spec in specs}

        assert WEB_SEARCH_CAPABILITY_ID in by_capability
        web_search_spec = by_capability[WEB_SEARCH_CAPABILITY_ID]
        assert web_search_spec.name == WEB_SEARCH_TOOL_SPEC.name
        assert web_search_spec.parameters == WEB_SEARCH_TOOL_SPEC.parameters
        assert web_search_spec.description.startswith(
            WEB_SEARCH_TOOL_SPEC.description
        )
        assert "Use when:" in web_search_spec.description
        assert "Avoid when:" in web_search_spec.description

    def test_includes_runtime_datetime(self, runtime) -> None:
        # "what time is it" contains tokens that match runtime.current_datetime capability
        specs = discover_tool_specs(runtime, text="what time is it")
        by_name = {spec.name: spec for spec in specs}

        assert "get_current_datetime" in by_name
        assert by_name["get_current_datetime"].capability_id == (
            "runtime.current_datetime"
        )

    def test_falls_back_to_generic_schema_for_unknown_tool_capability(
        self, runtime
    ) -> None:
        runtime.capability_registry.register(
            CapabilityDefinition(
                id="custom.made_up_capability",
                name="Custom Capability",
                description="A capability with no documented schema.",
                category=CapabilityCategory.TOOL,
                keywords=frozenset({"custom", "made", "up"}),
            )
        )

        specs = discover_tool_specs(runtime, text="custom made up capability")
        by_capability = {spec.capability_id: spec for spec in specs}

        assert "custom.made_up_capability" in by_capability
        generic_spec = by_capability["custom.made_up_capability"]
        assert generic_spec.name == "custom_made_up_capability"
        assert generic_spec.parameters["additionalProperties"] is True

    def test_filesystem_capabilities_use_their_own_documented_schema(
        self, runtime
    ) -> None:
        # "read a file" contains tokens that match filesystem.read capability
        specs = discover_tool_specs(runtime, text="read a file")
        by_capability = {spec.capability_id: spec for spec in specs}

        assert "filesystem.read" in by_capability
        read_spec = by_capability["filesystem.read"]
        assert read_spec.parameters["required"] == ["path"]

    def test_excludes_disabled_capabilities(self, runtime) -> None:
        runtime.capability_registry.disable("web.search")

        specs = discover_tool_specs(runtime, text="Hello!")

        assert WEB_SEARCH_TOOL_SPEC not in specs

    def test_excludes_non_tool_capabilities(self, runtime) -> None:
        specs = discover_tool_specs(runtime, text="Hello!")

        assert all(
            spec.capability_id != CHAT_CAPABILITY_ID for spec in specs
        )

    def test_no_signal_request_advertises_zero_tools(
        self, runtime
    ) -> None:
        """
        A conversational request with no relevance signal (e.g. "Hello!")
        must advertise zero tools. The old behavior of returning all
        enabled capabilities caused a massive prompt token explosion
        (≈178 capabilities → 177 tools → 46k prompt tokens).
        """

        specs = discover_tool_specs(runtime, text="Hello!")
        assert specs == ()

    def test_ordinary_statement_does_not_advertise_memory_remember(
        self, runtime
    ) -> None:
        specs = discover_tool_specs(runtime, text="My name is Pushpesh.")
        names = {spec.name for spec in specs}

        assert "memory_remember" not in names

    def test_explicit_memory_request_advertises_memory_remember(
        self, runtime
    ) -> None:
        specs = discover_tool_specs(
            runtime, text="Remember my name is Pushpesh."
        )
        names = {spec.name for spec in specs}

        assert "memory_remember" in names

    def test_identity_question_advertises_no_tools(self, runtime) -> None:
        """
        An identity question like "Who are you?" has no relevance signal
        for any capability, so zero tools should be advertised.
        """
        specs = discover_tool_specs(runtime, text="Who are you?")
        assert specs == ()

    def test_explicit_memory_request_advertises_memory_remember(
        self, runtime
    ) -> None:
        specs = discover_tool_specs(
            runtime, text="Remember my name is Pushpesh."
        )
        names = {spec.name for spec in specs}

        assert "memory_remember" in names

    def test_never_reintroduces_a_disabled_capability(self, runtime) -> None:
        runtime.capability_registry.disable("weather.current")

        specs = discover_tool_specs(runtime, text="What's the weather today?")
        names = {spec.name for spec in specs}

        assert "weather_current" not in names


class TestBuildChatGoal:
    def test_targets_chat_capability(self) -> None:
        goal = build_chat_goal(
            messages=(ChatMessage(role="user", content="hi"),),
            tools=(),
            on_token=None,
        )

        assert goal.capability_id == CHAT_CAPABILITY_ID

    def test_tool_calling_preferred_when_tools_are_offered(self) -> None:
        """
        AI Context Engineering supplies Planner's `tool_calling`
        signal structurally -- from the fact that a tool roster is
        being offered for this turn, never by pattern-matching the
        message text (Planner's former Requirement Inference
        framework has been removed; see `docs/architecture/
        Request_Understanding.md`). This is a partial override dict,
        never a full `ExecutionRequirements` instance.
        """

        goal = build_chat_goal(
            messages=(ChatMessage(role="user", content="hi"),),
            tools=(WEB_SEARCH_TOOL_SPEC,),
            on_token=None,
        )

        requirements = goal.metadata["execution_requirements"]
        assert isinstance(requirements, dict)
        assert requirements["tool_calling"] == "preferred"

    def test_tool_calling_absent_when_no_tools_are_offered(self) -> None:
        goal = build_chat_goal(
            messages=(ChatMessage(role="user", content="hi"),),
            tools=(),
            on_token=None,
        )

        requirements = goal.metadata["execution_requirements"]
        assert "tool_calling" not in requirements

    def test_execution_requirements_reflect_streaming(self) -> None:
        goal = build_chat_goal(
            messages=(ChatMessage(role="user", content="hi"),),
            tools=(),
            on_token=lambda fragment: None,
        )

        requirements = goal.metadata["execution_requirements"]
        assert requirements["streaming_required"] is True

    def test_execution_requirements_streaming_false_without_callback(
        self,
    ) -> None:
        goal = build_chat_goal(
            messages=(ChatMessage(role="user", content="hi"),),
            tools=(),
            on_token=None,
        )

        requirements = goal.metadata["execution_requirements"]
        assert requirements["streaming_required"] is False

    def test_latest_message_flows_into_goal_inputs(self) -> None:
        goal = build_chat_goal(
            messages=(
                ChatMessage(
                    role="user", content="What is the current time?"
                ),
            ),
            tools=(),
            on_token=None,
            latest_message="What is the current time?",
        )

        assert goal.inputs["message"] == "What is the current time?"

    def test_omitted_latest_message_leaves_inputs_without_message_key(
        self,
    ) -> None:
        goal = build_chat_goal(
            messages=(ChatMessage(role="user", content="hi"),),
            tools=(),
            on_token=None,
        )

        assert "message" not in goal.inputs

    def test_provider_request_builder_produces_chat_request(
        self,
    ) -> None:
        messages = (ChatMessage(role="user", content="hi"),)
        tools = (WEB_SEARCH_TOOL_SPEC,)

        fragments: list[str] = []
        goal = build_chat_goal(
            messages=messages,
            tools=tools,
            on_token=fragments.append,
        )

        assert goal.provider_request_builder is not None
        request = goal.provider_request_builder(None, None)  # type: ignore[arg-type]

        assert isinstance(request, ChatRequest)
        assert request.messages == messages
        assert request.tools == tools
        assert request.on_token is not None
        request.on_token("chunk")
        assert fragments == ["chunk"]

    def test_explicit_goal_id_is_used(self) -> None:
        goal = build_chat_goal(
            messages=(), tools=(), on_token=None, goal_id="fixed-id"
        )

        assert goal.id == "fixed-id"


class TestBuildAssistantSystemPrompt:
    """
    PARIKA Memory Subsystem Refactor Requirement A/Identity Ownership:
    every configured `[assistant]` field the assistant must be aware
    of -- including `nick_name` -- must be present in the system
    prompt built from Configuration, since this (not Memory) is the
    assistant's only source of truth for its own identity.
    """

    def test_includes_configured_name(self, runtime) -> None:
        prompt = build_assistant_system_prompt(runtime.configuration)

        assert "PARIKA" in prompt

    def test_includes_configured_nickname(self, runtime) -> None:
        prompt = build_assistant_system_prompt(runtime.configuration)

        assert "PARI" in prompt

    def test_includes_configured_creator(self, runtime) -> None:
        prompt = build_assistant_system_prompt(runtime.configuration)

        assert runtime.configuration.get("assistant.creator") in prompt

    def test_instructs_identity_questions_answered_directly(self, runtime) -> None:
        # `ai_context/behavior.py`'s fixed instruction reads "Your
        # identity is fully defined above. Answer identity questions
        # only from it; never use a tool." -- the literal "own
        # identity" phrasing this assertion originally checked for was
        # intentionally moved out of the base prompt into Memory's/
        # Web Search's own Tool Affordance Contracts as part of the
        # Capability Independence refactor (see
        # docs/architecture/Request_Understanding.md section 4.9's
        # "AI Context Engineering never says..." table); the base
        # prompt still instructs identity questions be answered
        # directly from the identity block, just with different
        # wording.
        prompt = build_assistant_system_prompt(runtime.configuration)

        assert "identity is fully defined above" in prompt.lower()
        assert "never" in prompt.lower()

    def test_includes_the_general_model_selection_policy(self, runtime) -> None:
        prompt = build_assistant_system_prompt(runtime.configuration)

        assert "model_selection_hint" in prompt

    def test_includes_the_general_reasoning_policy(self, runtime) -> None:
        """
        Strictly Explicit Memory guidance (e.g. "only call this when
        the user explicitly asks...") has moved out of the base system
        prompt entirely, into `memory.remember`'s own Tool Affordance
        Contract (see `TestMemoryRememberToolAffordanceContract`) --
        the base prompt now only carries the capability-independent
        Reasoning Policy plus Assistant Identity/Behavior text.
        """

        prompt = build_assistant_system_prompt(runtime.configuration)

        assert "reason in this order" in prompt.lower()
        assert "never call a tool simply because it is available" in prompt.lower()

    def test_omits_nickname_sentence_when_not_configured(self) -> None:
        from parika.core.configuration.configuration import Configuration

        configuration = Configuration()
        # Deliberately unloaded: every `.get()` call falls back to its
        # explicit default, so `assistant.nick_name` resolves to "".
        prompt = build_assistant_system_prompt(configuration)

        assert "your nickname" not in prompt.lower()


class TestMemoryRememberToolAffordanceContract:
    """
    The `memory.remember` Tool Affordance Contract (owned by the
    Memory Tool itself -- see `parika.tools.memory.manifest.
    MEMORY_TOOL_AFFORDANCES`) is the prompt-level half of Requirements
    A/B/C (Assistant Identity Protection, Strictly Explicit Memory,
    Precision Storage) -- see `identity_guard.py`/`driver.py` for the
    deterministic backstops. Its `use_when`/`avoid_when` fields carry
    what used to be hardcoded inside AI Context Engineering's system
    prompt; they are asserted here directly, and via the actual
    composed tool-spec description `tool_context.py` builds from them.
    """

    def test_requires_explicit_user_request(self) -> None:
        use_when = _MEMORY_REMEMBER_AFFORDANCE["use_when"].lower()

        assert "explicitly asks you to remember" in use_when

    def test_forbids_storing_self_identity(self) -> None:
        avoid_when = _MEMORY_REMEMBER_AFFORDANCE["avoid_when"].lower()

        assert "about your own identity" in avoid_when

    def test_content_parameter_requires_precision(self) -> None:
        content_description = _MEMORY_REMEMBER_AFFORDANCE["parameters"]["properties"][
            "content"
        ]["description"].lower()

        assert "nothing more" in content_description

    def test_composed_description_includes_use_and_avoid_guidance(
        self, runtime
    ) -> None:
        """
        `tool_context._compose_description()` assembles the Tool
        Affordance Contract's fields into the single description
        string actually advertised to the model -- verified here
        through the real `discover_tool_specs()` pipeline rather than
        by re-implementing the composition logic in this test.
        """

        specs = discover_tool_specs(
            runtime, text="Remember my name is Pushpesh."
        )
        by_capability = {spec.capability_id: spec for spec in specs}
        description = by_capability[MEMORY_CAPABILITY_REMEMBER].description.lower()

        assert "use when" in description
        assert "avoid when" in description
        assert "explicitly asks you to remember" in description
