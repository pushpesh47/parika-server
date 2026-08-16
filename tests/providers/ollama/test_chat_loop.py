"""
Unit tests for `parika.providers.ollama.chat_loop.run_chat_loop`.

`ToolCallResolver` is faked here (a plain scripted stand-in, not a
real Brain-backed resolver) so the loop's own orchestration -
especially repeated deterministic tool failure detection - is
exercised in isolation, independent of `tool_calling.py` or Brain.
"""

from __future__ import annotations

import json

import pytest

from parika.providers.ollama.chat_loop import run_chat_loop
from parika.providers.ollama.exceptions import OllamaToolCallError
from parika.providers.ollama.messages import (
    OllamaMessage,
    OllamaToolCall,
    OllamaToolSpec,
)

TOOL_SPEC = OllamaToolSpec(
    name="get_current_datetime",
    description="Get the current date and time.",
    capability_id="runtime.current_datetime",
    parameters={"type": "object", "properties": {}},
)

TOOLS_BY_NAME = {TOOL_SPEC.name: TOOL_SPEC}


class _ScriptedResolver:
    """
    Records every call it receives and returns scripted
    `(content, capability_id, succeeded)` results in order, so a test
    can assert exactly how many times (and with what arguments) the
    resolver was actually invoked.
    """

    def __init__(self, *scripted: tuple[str, str | None, bool]) -> None:
        self._scripted = list(scripted)
        self.calls: list[OllamaToolCall] = []

    def resolve(
        self,
        call: OllamaToolCall,
        tools_by_name: dict[str, OllamaToolSpec],
    ) -> tuple[str, str | None, bool]:
        self.calls.append(call)
        return self._scripted.pop(0)


def _final_answer(text: str) -> OllamaMessage:
    return OllamaMessage(role="assistant", content=text)


def _tool_call(
    name: str,
    arguments: dict[str, object],
    *,
    content: str = "",
) -> OllamaMessage:
    return OllamaMessage(
        role="assistant",
        content=content,
        tool_calls=(OllamaToolCall(name=name, arguments=arguments),),
    )


class TestRepeatedDeterministicFailureDetection:
    def test_identical_repeat_of_a_failed_call_is_not_re_executed(
        self,
    ) -> None:
        failure = json.dumps({"error": "Unknown timezone 'USA'."})

        turns = [
            (_tool_call("get_current_datetime", {"timezone": "USA"}), {}),
            (_tool_call("get_current_datetime", {"timezone": "USA"}), {}),
            (_final_answer("Sorry, I could not resolve that timezone."), {}),
        ]

        resolver = _ScriptedResolver(
            (failure, "runtime.current_datetime", False),
        )

        def chat_once(messages):
            return turns.pop(0)

        response = run_chat_loop(
            model_id="test-model",
            messages=[],
            tools_by_name=TOOLS_BY_NAME,
            max_tool_iterations=5,
            chat_once=chat_once,
            tool_call_resolver=resolver,
        )

        # The resolver was only ever actually invoked once: the
        # second, identical call was short-circuited.
        assert len(resolver.calls) == 1

        assert len(response.tool_invocations) == 2
        assert response.tool_invocations[0].content == failure
        assert response.tool_invocations[0].succeeded is False
        # The cached failure result was fed back verbatim.
        assert response.tool_invocations[1].content == failure
        assert response.tool_invocations[1].succeeded is False
        assert (
            response.tool_invocations[1].capability_id
            == "runtime.current_datetime"
        )

        assert response.message.content == (
            "Sorry, I could not resolve that timezone."
        )

    def test_different_arguments_always_execute(self) -> None:
        turns = [
            (_tool_call("get_current_datetime", {"timezone": "USA"}), {}),
            (_tool_call("get_current_datetime", {"timezone": "IST"}), {}),
            (_final_answer("Done."), {}),
        ]

        resolver = _ScriptedResolver(
            (
                json.dumps({"error": "Unknown timezone 'USA'."}),
                "runtime.current_datetime",
                False,
            ),
            (
                json.dumps({"date": "2026-07-30"}),
                "runtime.current_datetime",
                True,
            ),
        )

        def chat_once(messages):
            return turns.pop(0)

        run_chat_loop(
            model_id="test-model",
            messages=[],
            tools_by_name=TOOLS_BY_NAME,
            max_tool_iterations=5,
            chat_once=chat_once,
            tool_call_resolver=resolver,
        )

        # Both calls genuinely differ in arguments, so both were
        # executed - never short-circuited.
        assert len(resolver.calls) == 2
        assert resolver.calls[0].arguments == {"timezone": "USA"}
        assert resolver.calls[1].arguments == {"timezone": "IST"}

    def test_different_arguments_across_turns_never_dedup(self) -> None:
        """
        Successful-call deduplication (see
        `TestRepeatedDeterministicSuccessDetection`) never applies to
        genuinely different arguments, even for the same tool name -
        the model calling the same idempotent tool twice on purpose,
        for two different timezones, always executes both times.
        """

        turns = [
            (_tool_call("get_current_datetime", {"timezone": "IST"}), {}),
            (_tool_call("get_current_datetime", {"timezone": "UTC"}), {}),
            (_final_answer("Done."), {}),
        ]

        resolver = _ScriptedResolver(
            (json.dumps({"date": "2026-07-30"}), "runtime.current_datetime", True),
            (json.dumps({"date": "2026-07-30"}), "runtime.current_datetime", True),
        )

        def chat_once(messages):
            return turns.pop(0)

        run_chat_loop(
            model_id="test-model",
            messages=[],
            tools_by_name=TOOLS_BY_NAME,
            max_tool_iterations=5,
            chat_once=chat_once,
            tool_call_resolver=resolver,
        )

        assert len(resolver.calls) == 2

    def test_genuinely_varying_failures_still_exhaust_the_iteration_budget(
        self,
    ) -> None:
        """
        A model that keeps requesting the *same tool* but with a
        genuinely *different* argument every single turn (so neither
        the deterministic-failure/-success caches nor no-op turn
        detection ever short-circuits it) still eventually exhausts
        `max_tool_iterations` and raises, rather than looping forever.
        """

        def chat_once(messages):
            # A fresh, never-before-seen timezone value every turn,
            # so this call is never treated as a repeat.
            call_index = sum(
                1 for message in messages if message.role == "assistant"
            )
            return (
                _tool_call(
                    "get_current_datetime",
                    {"timezone": f"Zone/{call_index}"},
                ),
                {},
            )

        resolver = _ScriptedResolver(
            *(
                (
                    json.dumps({"error": "Unknown timezone."}),
                    "runtime.current_datetime",
                    False,
                )
                for _ in range(10)
            )
        )

        with pytest.raises(OllamaToolCallError):
            run_chat_loop(
                model_id="test-model",
                messages=[],
                tools_by_name=TOOLS_BY_NAME,
                max_tool_iterations=3,
                chat_once=chat_once,
                tool_call_resolver=resolver,
            )

        # Every turn requested genuinely different arguments, so the
        # tool really was executed on every one of the permitted
        # iterations - none of them were short-circuited.
        assert len(resolver.calls) == 4


class TestRepeatedDeterministicSuccessDetection:
    def test_identical_repeat_of_a_successful_call_is_not_re_executed(
        self,
    ) -> None:
        """
        Regression test for Phase 1 Item 4 ("Fix Repeated Tool
        Invocation"): once a tool call has succeeded, an identical
        repeat of that exact call - same tool, same arguments - is
        served the cached result instead of being executed again.
        """

        success = json.dumps({"date": "2026-07-30"})

        turns = [
            (_tool_call("get_current_datetime", {"timezone": "IST"}), {}),
            (
                _tool_call(
                    "get_current_datetime",
                    {"timezone": "IST"},
                    content="Let me double check that.",
                ),
                {},
            ),
            (_final_answer("It is 2026-07-30."), {}),
        ]

        resolver = _ScriptedResolver(
            (success, "runtime.current_datetime", True),
        )

        def chat_once(messages):
            return turns.pop(0)

        response = run_chat_loop(
            model_id="test-model",
            messages=[],
            tools_by_name=TOOLS_BY_NAME,
            max_tool_iterations=5,
            chat_once=chat_once,
            tool_call_resolver=resolver,
        )

        # The resolver was only ever actually invoked once: the
        # second, identical call was short-circuited and served the
        # cached successful result instead.
        assert len(resolver.calls) == 1

        assert len(response.tool_invocations) == 2
        assert response.tool_invocations[0].content == success
        assert response.tool_invocations[0].succeeded is True
        assert response.tool_invocations[1].content == success
        assert response.tool_invocations[1].succeeded is True
        assert (
            response.tool_invocations[1].capability_id
            == "runtime.current_datetime"
        )

        assert response.message.content == "It is 2026-07-30."

    def test_duplicate_calls_within_a_single_turn_are_deduped(self) -> None:
        """
        The exact same scenario also applies within a single
        assistant turn that happens to request the identical tool
        call twice (a plausible model quirk, not just across turns).
        """

        success = json.dumps({"date": "2026-07-30"})

        duplicate_calls_message = OllamaMessage(
            role="assistant",
            tool_calls=(
                OllamaToolCall(
                    name="get_current_datetime", arguments={"timezone": "IST"}
                ),
                OllamaToolCall(
                    name="get_current_datetime", arguments={"timezone": "IST"}
                ),
            ),
        )

        turns = [
            (duplicate_calls_message, {}),
            (_final_answer("Done."), {}),
        ]

        resolver = _ScriptedResolver(
            (success, "runtime.current_datetime", True),
        )

        def chat_once(messages):
            return turns.pop(0)

        response = run_chat_loop(
            model_id="test-model",
            messages=[],
            tools_by_name=TOOLS_BY_NAME,
            max_tool_iterations=5,
            chat_once=chat_once,
            tool_call_resolver=resolver,
        )

        assert len(resolver.calls) == 1
        assert len(response.tool_invocations) == 2
        assert all(
            invocation.succeeded for invocation in response.tool_invocations
        )


class TestNoOpTurnDetection:
    def test_identical_consecutive_tool_calling_turns_terminate_early(
        self,
    ) -> None:
        """
        Regression test for Phase 1 Item 3 ("Fix Provider
        Conversation Loop"): a model that keeps requesting the exact
        same tool call with the exact same (normalized) reasoning
        content, never incorporating any tool result, terminates the
        loop early instead of grinding through the remaining
        `max_tool_iterations` budget for no further progress.

        The *first* repeat (the 2nd occurrence overall) is still let
        through, so the deterministic-success cache gets to feed its
        cached result back once (see `NO_OP_REPEAT_LIMIT`'s own
        docstring); only the *second* repeat (the 3rd occurrence)
        triggers early termination.
        """

        call = _tool_call(
            "get_current_datetime", {"timezone": "IST"}, content=""
        )

        resolver = _ScriptedResolver(
            (json.dumps({"date": "2026-07-30"}), "runtime.current_datetime", True),
        )

        call_count = 0

        def chat_once(messages):
            nonlocal call_count
            call_count += 1
            return call, {}

        response = run_chat_loop(
            model_id="test-model",
            messages=[],
            tools_by_name=TOOLS_BY_NAME,
            max_tool_iterations=10,
            chat_once=chat_once,
            tool_call_resolver=resolver,
        )

        # Terminated after the third, twice-repeated turn was
        # detected - nowhere near exhausting the 10-iteration budget.
        assert call_count == 3
        assert not response.message.tool_calls
        assert response.done is True
        # Only the very first occurrence actually executed the tool;
        # the second occurrence was served the cached success.
        assert len(resolver.calls) == 1

    def test_whitespace_and_casing_only_differences_still_count_as_a_repeat(
        self,
    ) -> None:
        """
        No-op detection compares *normalized* content, so a
        superficially different but substantively identical
        reasoning string (extra whitespace, different casing) is
        still recognized as the same repeated turn.
        """

        turns = [
            _tool_call(
                "get_current_datetime",
                {"timezone": "IST"},
                content="Checking the time now.",
            ),
            _tool_call(
                "get_current_datetime",
                {"timezone": "IST"},
                content="  Checking   the time now.  ",
            ),
            _tool_call(
                "get_current_datetime",
                {"timezone": "IST"},
                content="CHECKING THE TIME NOW.",
            ),
        ]

        resolver = _ScriptedResolver(
            (json.dumps({"date": "2026-07-30"}), "runtime.current_datetime", True),
        )

        call_count = 0

        def chat_once(messages):
            nonlocal call_count
            message = turns[call_count]
            call_count += 1
            return message, {}

        response = run_chat_loop(
            model_id="test-model",
            messages=[],
            tools_by_name=TOOLS_BY_NAME,
            max_tool_iterations=10,
            chat_once=chat_once,
            tool_call_resolver=resolver,
        )

        assert call_count == 3
        assert not response.message.tool_calls

    def test_genuinely_different_reasoning_content_is_not_a_no_op(
        self,
    ) -> None:
        """
        The exact same tool call requested twice in a row with
        genuinely different reasoning content each time is never
        treated as a no-op - it keeps iterating normally, relying on
        successful-call deduplication (not early termination) to
        avoid re-executing the tool itself.
        """

        turns = [
            (
                _tool_call(
                    "get_current_datetime",
                    {"timezone": "IST"},
                    content="Let me check the current time.",
                ),
                {},
            ),
            (
                _tool_call(
                    "get_current_datetime",
                    {"timezone": "IST"},
                    content="Let me verify that timezone is correct.",
                ),
                {},
            ),
            (_final_answer("It is 2026-07-30."), {}),
        ]

        resolver = _ScriptedResolver(
            (json.dumps({"date": "2026-07-30"}), "runtime.current_datetime", True),
        )

        def chat_once(messages):
            return turns.pop(0)

        response = run_chat_loop(
            model_id="test-model",
            messages=[],
            tools_by_name=TOOLS_BY_NAME,
            max_tool_iterations=5,
            chat_once=chat_once,
            tool_call_resolver=resolver,
        )

        # Not treated as a no-op: the loop continued to the final
        # answer rather than terminating early on the second turn.
        assert response.message.content == "It is 2026-07-30."
        # But the tool call itself, being identical, was still
        # deduplicated by TestRepeatedDeterministicSuccessDetection's
        # own mechanism.
        assert len(resolver.calls) == 1
