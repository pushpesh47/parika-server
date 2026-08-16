"""
PARIKA AI Context Engineering - Goal Builder

Owns ONLY building the `Goal` Brain should plan and execute for one
chat turn, from already-built `messages`/`tools`. Never decides
identity, conversation, memory, knowledge, capability, or tool content
itself (see the other `ai_context` submodules for those).

This module is AI Context Engineering's Prompt Engineering
responsibility's Final Prompt Assembly step: Context Engineering
(`context_builder.py`, `session_context.py`, `conversation.py`) has
already decided *what* information this turn's Conversation/Memory/
Knowledge/Retrieved Context contains, folded into the `messages`
argument received here; Prompt Engineering's other modules
(`prompt_builder.py`/`identity.py`/`behavior.py`/`constraints.py`/
`reasoning_policy.py`/`model_selection_policy.py`, `tool_context.py`,
`worker_inventory.py`) have already decided *how* that information --
plus Assistant Identity, Behavior, Constraints, Reasoning Policy,
Model Selection Policy, Worker Inventory, and Tool Descriptions -- is
presented. This module owns only the final step: assembling all of it
into the one concrete request the Provider will receive, and
measuring that one complete, final assembly exactly once (see
`_estimate_prompt_tokens()` below) -- never summing named parts
individually, so any future Prompt Engineering contributor
automatically participates in the measurement the moment it is folded
into `messages`/`tools`, with no separate estimation bookkeeping to
remember.

Also owns injecting the Worker Model Inventory (see
`worker_inventory.py`) into the final `ChatRequest`, inside the
`provider_request_builder` closure Planner invokes at
`planner.py:676` -- strictly *after* Planner has already selected the
routing model (`planner.py:666-667`) and strictly *before* the request
is dispatched. This is what lets the inventory exclude exactly the
selected routing model with no second selection pass: the closure
receives that exact, already-selected `ProviderModel` instance as its
own `model` argument, and simply omits it while rendering the
inventory from the same live `ProviderManager` every other consumer
already reads from.

Builds the provider-independent `ChatRequest` (`parika.core
.provider_manager.chat_request`), never a concrete provider's own
request type: the selected Provider's driver (e.g.
`OllamaProviderDriver.execute()`, via `providers.ollama.chat_adapter`)
converts it into its own wire-specific request at the provider
boundary. `_build_provider_request()`/`_estimate_prompt_tokens()`
below are, deliberately, the only two places in this module that
build/measure a `ChatMessage`/`ToolSpec`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import uuid4

from parika.core.brain.context_engine import HeuristicTokenEstimator, TokenEstimator
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.planner.goal import ROUTING_GOAL_METADATA_KEY, Goal
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.tool_spec import ToolSpec
from parika.modules.chat.driver import CHAT_CAPABILITY_ID

from .worker_inventory import render_worker_inventory

_PROMPT_TOKEN_ESTIMATOR: TokenEstimator = HeuristicTokenEstimator()
"""
Shared `TokenEstimator` used to measure one turn's complete assembled
prompt (see `_estimate_prompt_tokens()`) -- the same `TokenEstimator`
Protocol/default implementation Brain's own Context Budgeting already
uses (`parika.core.brain.context_engine`), reused here rather than
reimplemented.
"""


def build_chat_goal(
    *,
    messages: tuple[ChatMessage, ...],
    tools: tuple[ToolSpec, ...],
    on_token: Callable[[str], None] | None,
    latest_message: str | None = None,
    goal_id: str | None = None,
    provider_manager: ProviderManager | None = None,
) -> Goal:
    """
    Build the Goal Brain should plan and execute for one chat turn.

    This is where AI Context Engineering supplies Planner's
    `ExecutionRequirements` override (see `Goal.metadata
    ["execution_requirements"]` and `model_selection/requirements.py`'s
    override precedence): a structural `tool_calling="preferred"`
    signal whenever `tools` is non-empty, derived purely from the
    fact that a tool roster is being offered for this turn -- never
    from pattern-matching the message text itself. `latest_message` is
    still threaded into `Goal.inputs["message"]` purely for
    observability/diagnostics; no Planner code reads it for inference.

    Args:
        messages:
            Full conversation history, oldest first, ending with the
            newest user message.

        tools:
            Tool specifications to advertise for native tool calling.

        on_token:
            Optional callback invoked with each streamed content
            fragment of the model's final answer.

        latest_message:
            The newest user-authored message text, when known. Placed
            into `Goal.inputs["message"]` for observability/
            diagnostics only. Passing `None` (e.g. for a non-text-
            driven caller) has no other effect.

        goal_id:
            Optional explicit Goal identifier. A random one is
            generated when omitted.

        provider_manager:
            Optional `ProviderManager`, used only to render the Worker
            Model Inventory (see `worker_inventory.py`) once Planner
            has selected this Goal's own routing model. `None` (the
            default) skips inventory rendering entirely, producing
            exactly the same `ChatRequest` as before this parameter
            existed -- fully backward compatible.

    Returns:
        A Goal targeting the `chat.respond` Capability with a
        `provider_request_builder` that constructs a
        provider-independent `ChatRequest` once Planner has selected a
        Provider model.
    """

    def _build_provider_request(
        resolution: CapabilityResolution,
        model: ProviderModel,
    ) -> ProviderRequest:
        final_messages = _with_worker_inventory(messages, provider_manager, model)

        estimated_prompt_tokens = _estimate_prompt_tokens(
            final_messages, tools, estimator=_PROMPT_TOKEN_ESTIMATOR
        )

        return ChatRequest(
            messages=final_messages,
            tools=tools,
            on_token=on_token,
            options=RequestOptions(
                estimated_prompt_tokens=estimated_prompt_tokens
            ),
        )

    inputs: dict[str, object] = {"message_count": len(messages)}

    if latest_message is not None:
        inputs["message"] = latest_message

    execution_requirements: dict[str, object] = {
        "streaming_required": on_token is not None,
    }

    if tools:
        execution_requirements["tool_calling"] = "preferred"

    return Goal(
        id=goal_id or uuid4().hex,
        capability_id=CHAT_CAPABILITY_ID,
        inputs=inputs,
        provider_request_builder=_build_provider_request,
        metadata={
            "execution_requirements": execution_requirements,
            # Marks this Goal's selection as the *routing model*
            # selection, so `[routing_model] mode = "fixed"` may
            # short-circuit straight to a pinned model for it (see
            # `ROUTING_GOAL_METADATA_KEY`'s docstring). Worker Goals
            # submitted by Tool drivers never set this key, so fixed
            # routing never affects worker model selection.
            ROUTING_GOAL_METADATA_KEY: True,
        },
    )


def _with_worker_inventory(
    messages: tuple[ChatMessage, ...],
    provider_manager: ProviderManager | None,
    routing_model: ProviderModel | None,
) -> tuple[ChatMessage, ...]:
    """
    Render the Worker Model Inventory (excluding `routing_model`, the
    model Planner just selected for this very Goal) and splice it in
    immediately before the newest message -- the same placement
    convention Memory/Knowledge context injection already uses (see
    `ai_context.conversation.assemble_conversation_messages()`).

    Returns `messages` unchanged when `provider_manager` is `None`
    (no inventory was requested) or when there are no other models to
    describe -- never injects an empty message.
    """

    if provider_manager is None:
        return messages

    inventory_text = render_worker_inventory(
        provider_manager.get_all(), exclude=routing_model
    )

    if not inventory_text:
        return messages

    inventory_message = ChatMessage(role="system", content=inventory_text)

    if not messages:
        return (inventory_message,)

    return (*messages[:-1], inventory_message, messages[-1])


def _estimate_prompt_tokens(
    messages: tuple[ChatMessage, ...],
    tools: tuple[ToolSpec, ...],
    *,
    estimator: TokenEstimator,
) -> int:
    """
    Estimate the complete, already-fully-assembled prompt's total
    token cost using `estimator` -- every message's role+content plus
    every advertised tool's full JSON schema, the same two
    ingredients the `ChatRequest` built by `_build_provider_request()`
    above is constructed from.

    Called exactly once, from `_build_provider_request()`, after
    Worker Inventory has already been spliced into `messages` -- i.e.
    after every Prompt Engineering ingredient (Assistant Identity,
    Behavior, Constraints, Reasoning Policy, Model Selection Policy,
    Worker Inventory, Tool Descriptions) and every Context Engineering
    ingredient (Conversation, Memory, Knowledge, Session Retrieval)
    that this turn's pipeline decided to include has already been
    folded into `messages`/`tools`, by the exact same call sites that
    already exist today. This deliberately measures the one final,
    concrete artifact rather than summing named parts (identity +
    behavior + constraints + worker_inventory + ...): any future
    Prompt Engineering contributor that gets folded into `messages`/
    `tools` upstream of this call -- exactly like every existing
    contributor already is -- automatically participates, with no
    change required here.

    Operates on the provider-independent `ChatMessage`/`ToolSpec`
    shapes, not any concrete provider's own wire payload: this is a
    coarse, provider-independent estimate of the assembled prompt's
    size (the same heuristic `HeuristicTokenEstimator` applies
    elsewhere), not a measurement of any one provider's actual wire
    bytes -- a provider that adds its own wire-format overhead (e.g.
    Ollama's `{"type": "function", ...}` tool-schema nesting) may
    reasonably differ from this estimate by a small, structural
    margin.
    """

    parts: list[str] = []

    for message in messages:
        parts.append(message.role)
        parts.append(message.content)

    for tool in tools:
        parts.append(
            json.dumps(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                },
                separators=(",", ":"),
            )
        )

    return estimator.estimate("\n".join(parts))
