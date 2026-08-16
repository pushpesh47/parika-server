"""
PARIKA Interfaces - Chat Capability Gateway (AI Context Engineering Orchestration)

Thin orchestration layer over PARIKA's AI Context Engineering
subsystem (`parika/interfaces/ai_context/`). Every function in this
module delegates its actual implementation to exactly one
`ai_context` submodule and contains no implementation logic of its
own -- Identity, Behavior, Constraints, Conversation, Memory,
Knowledge, Capability Context, Tool Context, Session Context, and Goal
Building each live in their own single-responsibility module; see
`ai_context/__init__.py` for the full list and
`docs/architecture/Request_Understanding.md` for the complete design.

The pipeline `InterfaceSession._submit_text()` drives through this
module, per turn:

    build_assistant_system_prompt()   (session construction time only)
        -> ai_context.prompt_builder
    discover_tool_specs()
        -> ai_context.capability_context + ai_context.tool_context
    assemble_context_messages()
        -> ai_context.context_builder (+ ai_context.memory/knowledge)
    assemble_session_retrieval_messages()
        -> ai_context.session_context
    build_chat_goal()
        -> ai_context.goal_builder
    Brain.handle()

This module never resolves capabilities, selects providers, or
executes anything itself - Brain, Planner, CapabilityExecutor, and the
selected Provider driver still own every one of those decisions
exactly as they do for any other Goal (see `PARIKA_Decision_Flow.md`).
This also holds for Assistant Identity: it is assembled entirely by
`ai_context`, before any Goal or ProviderRequest exists, as plain
conversation content - no Core component or Provider driver needs to
know it exists.
"""

from __future__ import annotations

from collections.abc import Callable

from parika.core.brain.context_engine import ContextBundle
from parika.core.configuration.configuration import Configuration
from parika.core.planner.goal import Goal
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.tool_spec import ToolSpec

from .ai_context import (
    capability_context,
    context_builder,
    conversation,
    goal_builder,
    prompt_builder,
    session_context,
    tool_context,
)
from .runtime import ParikaRuntime
from .session_store import SqliteSessionStore


def build_assistant_system_prompt(configuration: Configuration) -> str:
    """
    Build PARIKA's default Assistant Identity system prompt.

    Delegates entirely to `ai_context.prompt_builder.
    build_assistant_system_prompt()`; see that function's docstring
    for the full contract.

    Args:
        configuration:
            The already-loaded Configuration to read `[assistant]`
            values from.

    Returns:
        The composed identity + behavior + constraints text.
    """

    return prompt_builder.build_assistant_system_prompt(configuration)


def discover_tool_specs(
    runtime: ParikaRuntime, *, text: str
) -> tuple[ToolSpec, ...]:
    """
    Automatic Capability Discovery: build the tool specifications to
    advertise to the chat model for this turn.

    Orchestrates two `ai_context` steps: `capability_context.
    discover_capabilities()` discovers every enabled TOOL-category
    Capability directly from `runtime.capability_registry` and applies
    the read-only Capability Catalog retrieval/ranking pass (see
    `parika.core.capability_catalog`), with no hardcoded capability
    list; `tool_context.discover_tool_specs()` converts the retrieved
    subset into native tool-calling specs and applies the two
    fixed-scope memory-authorization gates (never capability routing)
    -- see that module's docstring. Registering a brand-new Capability
    requires no change anywhere in this pipeline: it is discovered and
    advertised automatically the moment it is registered and enabled.

    Args:
        runtime:
            Runtime whose CapabilityRegistry is queried.

        text:
            The current turn's message text, passed only to the
            authorization gates.

    Returns:
        One ToolSpec per authorized, enabled TOOL-category
        Capability.
    """

    definitions = capability_context.discover_capabilities(runtime, text=text)

    return tool_context.discover_tool_specs(definitions, text=text)


def assemble_context_messages(
    runtime: ParikaRuntime,
    *,
    text: str,
    session_id: str | None,
    conversation_message_count: int,
) -> tuple[tuple[ChatMessage, ...], ContextBundle | None]:
    """
    Automatically retrieve relevant Memory/Knowledge context for this
    turn.

    Delegates entirely to `ai_context.context_builder.
    assemble_context_messages()`; see that function's docstring for
    the full contract.
    """

    return context_builder.assemble_context_messages(
        runtime,
        text=text,
        session_id=session_id,
        conversation_message_count=conversation_message_count,
    )


def assemble_session_retrieval_messages(
    *,
    text: str,
    session_store: SqliteSessionStore | None,
    current_session_id: str | None,
    token_budget: int,
) -> tuple[ChatMessage, ...]:
    """
    Retrieve read-only excerpts from previously saved sessions, only
    for a turn explicitly asking about past/previous conversations.

    `token_budget` is the portion of this turn's Runtime Context
    Budget still available for previous-session excerpts (see
    `session_context.assemble_session_retrieval_messages()`'s
    docstring) -- it bounds how much is injected, never a fixed
    excerpt/session count.

    Delegates entirely to `ai_context.session_context.
    assemble_session_retrieval_messages()`; see that function's
    docstring for the full contract.
    """

    return session_context.assemble_session_retrieval_messages(
        text=text,
        session_store=session_store,
        current_session_id=current_session_id,
        token_budget=token_budget,
    )


def assemble_conversation_messages(
    history: tuple[ChatMessage, ...],
    injected_messages: tuple[ChatMessage, ...],
) -> tuple[ChatMessage, ...]:
    """
    Splice `injected_messages` (Memory/Knowledge/Session context)
    into the right position relative to the rolling conversation
    `history`, without mutating `history` itself.

    Delegates entirely to `ai_context.conversation.
    assemble_conversation_messages()`; see that function's docstring
    for the full contract.
    """

    return conversation.assemble_conversation_messages(history, injected_messages)


def build_chat_goal(
    *,
    messages: tuple[ChatMessage, ...],
    tools: tuple[ToolSpec, ...],
    on_token: Callable[[str], None] | None,
    latest_message: str | None = None,
    goal_id: str | None = None,
    runtime: ParikaRuntime | None = None,
) -> Goal:
    """
    Build the Goal Brain should plan and execute for one chat turn.

    Delegates entirely to `ai_context.goal_builder.build_chat_goal()`;
    see that function's docstring for the full contract.

    Args:
        runtime:
            Optional runtime, forwarded only as `runtime
            .provider_manager` so the built Goal's
            `provider_request_builder` can render the Worker Model
            Inventory once Planner selects this turn's routing model
            (see `goal_builder.build_chat_goal()`'s `provider_manager`
            parameter). Omitting it skips inventory rendering
            entirely -- fully backward compatible.
    """

    return goal_builder.build_chat_goal(
        messages=messages,
        tools=tools,
        on_token=on_token,
        latest_message=latest_message,
        goal_id=goal_id,
        provider_manager=runtime.provider_manager if runtime is not None else None,
    )
