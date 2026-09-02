"""
PARIKA Ollama Provider - Chat/Tool-Calling Loop

Runs the multi-turn `/api/chat` <-> tool-calling loop: repeatedly
calls `chat_once` and, whenever the model requests a tool call,
resolves it through a `ToolCallResolver` (which always calls
`Brain.handle()`, never bypassing Planner) before continuing the
conversation. Kept separate from `driver.py` so the driver itself
stays focused on orchestration (see `PARIKA_Core_Coding_Standards.md`
- File Size Guidelines).

Also detects two distinct kinds of unproductive repetition within a
single loop invocation, addressing Phase 1 Items 3/4 ("Fix Provider
Conversation Loop" / "Fix Repeated Tool Invocation"):

1. *Repeated deterministic tool failures*: if the model calls the
   exact same tool with the exact same arguments again after that
   exact call already failed, the cached failure result is fed back
   instead of re-executing the tool (see `_deterministic_call_key()`).
2. *Repeated deterministic tool successes*: symmetrically, if the
   model calls the exact same tool with the exact same arguments
   again after that exact call already *succeeded*, the cached
   successful result is fed back instead of re-executing the tool -
   this is the concrete fix for "one factual query sometimes invokes
   the same tool multiple times unnecessarily."
3. *No-op tool-calling turns*: if two consecutive tool-calling turns
   request the exact same set of tool calls with normalized-equal
   reasoning content - i.e. the model is not incorporating the tool
   results it already received - the loop terminates early with that
   turn's own content as the final answer, rather than continuing to
   iterate against `max_tool_iterations` for no further progress.

A genuinely different set of arguments, or genuinely different
reasoning content, is never affected by either detector - it always
executes/continues normally, even for the same tool name.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from .exceptions import OllamaToolCallError
from .messages import OllamaMessage, OllamaToolCall, OllamaToolSpec
from .responses import OllamaChatResponse, OllamaToolInvocation
from .tool_calling import ToolCallResolver

_logger = logging.getLogger(__name__)

_WHITESPACE_PATTERN = re.compile(r"\s+")

ChatOnceFn = Callable[[list[OllamaMessage]], tuple[OllamaMessage, dict[str, Any]]]

MAX_EMPTY_FINAL_RESPONSE_RETRIES = 1
"""
Some models occasionally produce a genuinely empty final answer (no
`tool_calls` and blank `content`) - an observed, non-deterministic
sampling outcome, not a deterministic bug - most often immediately
after a tool result was fed back. A blank final answer is never
useful to a caller, so it is retried a small, bounded number of times
(same messages, no changes) before being accepted as-is. This applies
generically to any final turn, regardless of whether a tool was
involved.
"""

NO_OP_REPEAT_LIMIT = 1
"""
Number of consecutive identical tool-calling turns (same tool-call
signature, same normalized content) tolerated before the loop treats
the pattern as a genuinely stuck no-op and terminates early.

Deliberately not zero: the *first* repeat of an identical turn is
still let through so the existing deterministic-failure/-success
caches (see module docstring) get to feed their cached result back to
the model exactly once, giving it a real chance to incorporate that
result (e.g. produce an apologetic final answer after a repeated
failure) before the loop gives up on it. Only a *second* consecutive
repeat - the model asking for the exact same thing a third time in a
row, having already been shown the exact same cached result once -
is treated as conclusively stuck.
"""


def run_chat_loop(
    *,
    model_id: str,
    messages: list[OllamaMessage],
    tools_by_name: dict[str, OllamaToolSpec],
    max_tool_iterations: int,
    chat_once: ChatOnceFn,
    tool_call_resolver: ToolCallResolver,
) -> OllamaChatResponse:
    """
    Run the chat/tool-calling loop to completion.

    Args:
        model_id:
            Identifier of the model being used, for the returned
            response.

        messages:
            Conversation history so far. Mutated in place as
            assistant and tool messages are appended.

        tools_by_name:
            Every tool specification advertised for this chat,
            keyed by the name advertised to the model.

        max_tool_iterations:
            Maximum number of tool-calling round trips permitted.

        chat_once:
            Callable performing a single `/api/chat` round trip,
            given the current message list.

        tool_call_resolver:
            Resolver used to execute any tool call the model
            requests.

    Returns:
        The final OllamaChatResponse once the model produces an
        answer with no further tool calls.

    Raises:
        OllamaToolCallError:
            If the model keeps requesting tool calls beyond
            `max_tool_iterations`.
    """

    tool_invocations: list[OllamaToolInvocation] = []
    previous_failures: dict[tuple[str, str], str] = {}
    previous_successes: dict[tuple[str, str], tuple[str, str | None]] = {}
    previous_turn_signature: frozenset[tuple[str, str]] | None = None
    previous_turn_content: str | None = None
    repeat_streak = 0

    for _ in range(max_tool_iterations + 1):
        assistant_message, metrics = _chat_once_with_empty_retry(
            model_id, messages, chat_once
        )

        if not assistant_message.tool_calls:
            return OllamaChatResponse(
                model_id=model_id,
                message=assistant_message,
                done=bool(metrics.get("done", True)),
                tool_invocations=tuple(tool_invocations),
                total_duration_ns=metrics.get("total_duration"),
                load_duration_ns=metrics.get("load_duration"),
                prompt_eval_duration_ns=metrics.get("prompt_eval_duration"),
                eval_duration_ns=metrics.get("eval_duration"),
                prompt_eval_count=metrics.get("prompt_eval_count"),
                eval_count=metrics.get("eval_count"),
            )

        current_turn_signature = frozenset(
            _deterministic_call_key(call)
            for call in assistant_message.tool_calls
        )
        current_turn_content = _normalize_for_comparison(
            assistant_message.content
        )

        if (
            previous_turn_signature is not None
            and current_turn_signature == previous_turn_signature
            and current_turn_content == previous_turn_content
        ):
            repeat_streak += 1
        else:
            repeat_streak = 0

        if repeat_streak > NO_OP_REPEAT_LIMIT:
            _logger.warning(
                "Detected a no-op tool-calling turn from model=%s: the "
                "exact same tool call(s) were requested again with "
                "equivalent reasoning content as the immediately "
                "preceding turn(s) - already fed back once via the "
                "deterministic-failure/-success caches - with no new "
                "information having changed in between; terminating "
                "the loop early instead of continuing to iterate.",
                model_id,
            )

            return OllamaChatResponse(
                model_id=model_id,
                message=OllamaMessage(
                    role="assistant",
                    content=assistant_message.content,
                ),
                done=True,
                tool_invocations=tuple(tool_invocations),
                total_duration_ns=metrics.get("total_duration"),
                load_duration_ns=metrics.get("load_duration"),
                prompt_eval_duration_ns=metrics.get("prompt_eval_duration"),
                eval_duration_ns=metrics.get("eval_duration"),
                prompt_eval_count=metrics.get("prompt_eval_count"),
                eval_count=metrics.get("eval_count"),
            )

        previous_turn_signature = current_turn_signature
        previous_turn_content = current_turn_content

        messages.append(assistant_message)

        for call in assistant_message.tool_calls:
            key = _deterministic_call_key(call)
            cached_failure = previous_failures.get(key)
            cached_success = previous_successes.get(key)

            if cached_failure is not None:
                spec = tools_by_name.get(call.name)
                content = cached_failure
                capability_id = spec.capability_id if spec is not None else None
                succeeded = False

                _logger.warning(
                    "Detected a repeated deterministic tool failure: "
                    "tool=%s was already called with the exact same "
                    "arguments and failed with the exact same error; "
                    "feeding back the previous failure instead of "
                    "executing it again.",
                    call.name,
                )
            elif cached_success is not None:
                content, capability_id = cached_success
                succeeded = True

                _logger.warning(
                    "Detected a repeated deterministic tool call: "
                    "tool=%s was already called with the exact same "
                    "arguments and succeeded; feeding back the "
                    "cached result instead of executing it again.",
                    call.name,
                )
            else:
                content, capability_id, succeeded = (
                    tool_call_resolver.resolve(call, tools_by_name)
                )

                if not succeeded:
                    previous_failures[key] = content
                else:
                    previous_successes[key] = (content, capability_id)

            tool_invocations.append(
                OllamaToolInvocation(
                    tool_call=call,
                    capability_id=capability_id,
                    succeeded=succeeded,
                    content=content,
                )
            )

            _logger.debug(
                "Submitting tool result: tool=%s capability=%s succeeded=%s",
                call.name,
                capability_id,
                succeeded,
            )

            _logger.debug(
                "Tool content sent back to model:\n%s",
                content,
            )

            messages.append(
                OllamaMessage(
                    role="tool",
                    content=content,
                    tool_call_id=call.id,
                    name=call.name,
                )
            )

    raise OllamaToolCallError(
        "Exceeded the maximum number of tool-calling iterations "
        f"({max_tool_iterations}) without the model producing a "
        "final answer."
    )


def _chat_once_with_empty_retry(
    model_id: str,
    messages: list[OllamaMessage],
    chat_once: ChatOnceFn,
) -> tuple[OllamaMessage, dict[str, Any]]:
    """
    Perform one `chat_once()` round trip, retrying a small, bounded
    number of times - with the exact same conversation, no changes -
    when the model produces a message with neither a tool call nor
    any content. A blank, tool-call-free response is never useful to
    a caller, and this is an observed, non-deterministic sampling
    outcome rather than a deterministic failure; retrying it here,
    inside a single round trip, keeps `run_chat_loop()`'s own
    `max_tool_iterations` budget completely unaffected.
    """

    assistant_message, metrics = chat_once(messages)
    retries = 0

    while (
        not assistant_message.tool_calls
        and not assistant_message.content.strip()
        and retries < MAX_EMPTY_FINAL_RESPONSE_RETRIES
    ):
        retries += 1

        _logger.warning(
            "Empty final response from model=%s; retrying (%d/%d) "
            "with the same conversation.",
            model_id,
            retries,
            MAX_EMPTY_FINAL_RESPONSE_RETRIES,
        )

        assistant_message, metrics = chat_once(messages)

    return assistant_message, metrics


def _normalize_for_comparison(content: str) -> str:
    """
    Normalize assistant message content for no-op/duplicate-turn
    comparison: collapse all runs of whitespace to a single space and
    lowercase the result. Used only for equality comparison in
    `run_chat_loop()` - the original `content` is always what is
    actually returned/streamed, never this normalized form. Deliberately
    conservative: it only smooths over incidental whitespace/casing
    differences, never paraphrases or fuzzy-matches genuinely different
    wording, so two turns with meaningfully different reasoning are
    never mistaken for a repeat.
    """

    return _WHITESPACE_PATTERN.sub(" ", content).strip().lower()


def _deterministic_call_key(call: OllamaToolCall) -> tuple[str, str]:
    """
    Build the identity key used to detect a repeated deterministic
    tool failure: the tool name together with a canonical (stable
    key order) JSON encoding of its arguments.

    Two calls to the same tool with genuinely different arguments
    always produce different keys, so they are never treated as
    repeats - only an exact, byte-for-byte repeat of a previously
    *failed* call is ever short-circuited (see `run_chat_loop()`).
    """

    canonical_arguments = json.dumps(
        dict(call.arguments), sort_keys=True, default=str
    )

    return (call.name, canonical_arguments)
