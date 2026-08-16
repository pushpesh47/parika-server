"""
Unit tests for the deterministic compact() function.

Phase A.5: `compact()` no longer slices by a fixed `recent_turns_kept`
turn count -- how many of the most recent turns are kept is driven
entirely by how many fit within `budget.usable_tokens`. Every message
in these tests uses `HeuristicTokenEstimator` (`len(text) // 4`,
minimum 1), so message content lengths are chosen to make the exact
token cost of each turn predictable.
"""

from __future__ import annotations

from parika.core.brain.context_engine.budget import TokenBudget
from parika.core.brain.context_engine.compaction import compact
from parika.core.brain.context_engine.message import ContextMessage
from parika.core.brain.context_engine.token_estimator import HeuristicTokenEstimator

_ESTIMATOR = HeuristicTokenEstimator()


def _turn(i: int) -> ContextMessage:
    # "turn N" is always <= 4 chars per estimator token, so each turn
    # costs exactly 1 estimated token -- makes budget math exact.
    return ContextMessage(role="user", content=f"t{i}")


def _messages(n: int) -> list[ContextMessage]:
    return [_turn(i) for i in range(n)]


def _budget(usable_tokens: int) -> TokenBudget:
    # reserved_for_response=0 and safety_reserve_tokens=0 make
    # `usable_tokens` exactly equal to `max_context_tokens`.
    return TokenBudget(
        max_context_tokens=usable_tokens,
        reserved_for_response=0,
        safety_reserve_tokens=0,
    )


class TestCompact:
    def test_keeps_all_messages_when_everything_fits_the_budget(self) -> None:
        messages = _messages(3)
        budget = _budget(100)

        result = compact(messages, budget=budget, estimator=_ESTIMATOR)

        assert result.dropped_count == 0
        assert list(result.messages) == messages

    def test_drops_middle_turns_beyond_the_token_budget(self) -> None:
        messages = _messages(10)
        # Each turn costs 1 token; a budget of 3 tokens keeps exactly
        # the 3 most recent turns.
        budget = _budget(3)

        result = compact(messages, budget=budget, estimator=_ESTIMATOR)

        assert result.dropped_count == 7
        # Placeholder + last 3 kept turns.
        assert len(result.messages) == 4
        assert "7 earlier turn(s) omitted" in result.messages[0].content
        assert [m.content for m in result.messages[1:]] == ["t7", "t8", "t9"]

    def test_system_messages_always_kept(self) -> None:
        messages = [
            ContextMessage(role="system", content="be helpful"),
            *_messages(10),
        ]
        budget = _budget(2)

        result = compact(messages, budget=budget, estimator=_ESTIMATOR)

        assert result.messages[0].role == "system"
        assert result.messages[0].content == "be helpful"

    def test_system_messages_reserve_budget_before_turns_are_kept(self) -> None:
        # A large system message consumes most of the budget, leaving
        # room for fewer recent turns than an equivalent turn-count
        # limit would have kept -- this is the whole point of Phase
        # A.5: no fixed turn count, only the remaining token budget.
        long_system_content = "s" * 400  # ~100 estimated tokens
        messages = [
            ContextMessage(role="system", content=long_system_content),
            *_messages(10),
        ]
        budget = _budget(103)  # 100 (system) + 3 (three 1-token turns)

        result = compact(messages, budget=budget, estimator=_ESTIMATOR)

        assert result.dropped_count == 7
        assert [m.content for m in result.messages[2:]] == ["t7", "t8", "t9"]

    def test_no_placeholder_when_nothing_dropped(self) -> None:
        messages = _messages(2)
        budget = _budget(100)

        result = compact(messages, budget=budget, estimator=_ESTIMATOR)

        assert all("omitted" not in m.content for m in result.messages)

    def test_estimated_tokens_uses_explicit_token_count_when_present(self) -> None:
        messages = [ContextMessage(role="user", content="x" * 400, token_count=1)]
        budget = _budget(100)

        result = compact(messages, budget=budget, estimator=_ESTIMATOR)

        assert result.estimated_tokens == 1

    def test_zero_usable_tokens_drops_everything_non_system(self) -> None:
        messages = _messages(5)
        budget = _budget(0)

        result = compact(messages, budget=budget, estimator=_ESTIMATOR)

        assert result.dropped_count == 5
        assert len(result.messages) == 1  # only the placeholder

    def test_larger_budget_keeps_more_turns_than_a_smaller_one(self) -> None:
        # Directly exercises "dynamic Runtime Context Budget
        # consumption": the same messages, compacted against a bigger
        # budget, keep strictly more turns.
        messages = _messages(10)

        small_result = compact(messages, budget=_budget(2), estimator=_ESTIMATOR)
        large_result = compact(messages, budget=_budget(8), estimator=_ESTIMATOR)

        assert small_result.dropped_count > large_result.dropped_count
