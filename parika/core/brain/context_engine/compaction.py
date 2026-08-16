"""
PARIKA Brain - Context Engine - Compaction

Deterministic, extractive history compaction: keeps every system
message plus as many of the most recent turns as fit within the
Runtime Context Budget (`budget.usable_tokens`), replacing dropped
middle turns with a short placeholder. Never calls a Provider and
never interprets the *meaning* of dropped content -- only mechanical
selection by role/position/token cost, exactly like `Brain.compact()`
is documented to behave by default.

Phase A.5 removed the fixed `recent_turns_kept` turn count this module
used to slice by: how many turns are kept is now driven entirely by
how many of them fit within `budget.usable_tokens`, so a larger
Runtime Context Budget (a model with a bigger context window) keeps
more history and a smaller one keeps less, never a hardcoded turn
count.

True abstractive summarization (turning dropped turns into an LLM-
written summary) is intentionally out of scope here: a caller wanting
that builds an explicit `chat.summarize` Goal and submits it through
the existing `Brain.handle()` pipeline, so Brain's context engine never
itself contains an LLM prompt loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .budget import TokenBudget
from .message import ContextMessage
from .token_estimator import TokenEstimator

_SYSTEM_ROLE = "system"


@dataclass(frozen=True, slots=True, kw_only=True)
class CompactionResult:
    """The result of one `compact()` call."""

    messages: tuple[ContextMessage, ...]
    dropped_count: int
    estimated_tokens: int


def _token_count(message: ContextMessage, *, estimator: TokenEstimator) -> int:
    return (
        message.token_count
        if message.token_count is not None
        else estimator.estimate(message.content)
    )


def compact(
    messages: "list[ContextMessage] | tuple[ContextMessage, ...]",
    *,
    budget: TokenBudget,
    estimator: TokenEstimator,
) -> CompactionResult:
    """
    Deterministically compact `messages` to fit within `budget`.

    Keeps every system-role message, plus as many of the most recent
    non-system messages as fit within `budget.usable_tokens` (after
    reserving room for the system messages themselves), working
    backwards from the newest message. If any non-system messages were
    dropped, they are replaced by one placeholder message summarizing
    only the count -- never their content.
    """

    system_messages = [m for m in messages if m.role == _SYSTEM_ROLE]
    other_messages = [m for m in messages if m.role != _SYSTEM_ROLE]

    system_tokens = sum(
        _token_count(message, estimator=estimator) for message in system_messages
    )
    remaining_budget = max(0, budget.usable_tokens - system_tokens)

    kept_reversed: list[ContextMessage] = []
    used_tokens = 0

    for message in reversed(other_messages):
        cost = _token_count(message, estimator=estimator)

        if used_tokens + cost > remaining_budget:
            break

        kept_reversed.append(message)
        used_tokens += cost

    kept = list(reversed(kept_reversed))
    dropped_count = len(other_messages) - len(kept)

    result_messages: list[ContextMessage] = list(system_messages)

    if dropped_count > 0:
        placeholder = ContextMessage(
            role=_SYSTEM_ROLE,
            content=f"[{dropped_count} earlier turn(s) omitted for length.]",
        )
        result_messages.append(placeholder)

    result_messages.extend(kept)

    estimated_tokens = sum(
        _token_count(message, estimator=estimator) for message in result_messages
    )

    return CompactionResult(
        messages=tuple(result_messages),
        dropped_count=dropped_count,
        estimated_tokens=estimated_tokens,
    )
