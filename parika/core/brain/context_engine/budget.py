"""
PARIKA Brain - Context Engine - Token Budget

Defines `TokenBudget` and its `[context_engine]` configuration loader,
following the exact `load_xxx_config(configuration)` pattern already
used by `model_selection/config.py` and `memory_manager/config.py`.

`TokenBudget` is the Runtime Context Budget applied here, before a
model has been selected: Context Assembly (`retrieval_ordering.py`)
and Compaction (`compaction.py`) use it to bound how much Memory/
Knowledge/conversation content they pack into a Goal, always reading
their ceiling/reservations from `[context_engine]` configuration
rather than any hardcoded value. Once Planner has actually selected a
model, the equivalent, authoritative computation for that specific
model happens in `provider_manager.context_budget
.resolve_runtime_context_budget()` (reusing this same
`[context_engine]` configuration), whose result is what a
ProviderDriver ultimately turns into a provider-specific context
parameter (e.g. Ollama's `num_ctx`). See
docs/architecture/PARIKA_Decision_Flow.md section 4.4 and
docs/architecture/Core_Component_Responsibilities.md sections 14 and
28 for the full Runtime Context Budget flow.

Phase A.5 removed every fixed-count prompt limitation this module used
to define (`recent_turns_kept`, `max_memories`, `max_knowledge_entries`,
`max_conversation_messages`): every prompt-context consumer now packs
as much relevant content as fits within `usable_tokens` alone, never a
hardcoded entry/turn count. Only the token-denominated inputs that
PARIKA itself genuinely owns and that cannot be derived from a
selected model (because Brain does not know which model Planner will
select until after `plan()` returns -- see the class docstring below)
remain here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parika.core.configuration.configuration import Configuration

_DEFAULT_MAX_CONTEXT_TOKENS: int = 8192
_DEFAULT_RESERVED_FOR_RESPONSE: int = 1024
_DEFAULT_SAFETY_RESERVE_TOKENS: int = 256
_DEFAULT_WARNING_THRESHOLD: float = 0.8


@dataclass(frozen=True, slots=True, kw_only=True)
class TokenBudget:
    """
    A token budget for one context-assembly or compaction operation.

    `max_context_tokens` is a config-driven default ceiling, not the
    live selected model's actual context window -- Brain does not know
    which model Planner will select until after `plan()` returns (see
    the design document's provider-aware-sizing note, section 7.3).
    """

    max_context_tokens: int = _DEFAULT_MAX_CONTEXT_TOKENS
    reserved_for_response: int = _DEFAULT_RESERVED_FOR_RESPONSE
    safety_reserve_tokens: int = _DEFAULT_SAFETY_RESERVE_TOKENS
    """
    Additional headroom held back from `usable_tokens`, on top of
    `reserved_for_response`, to absorb token-estimation error -- the
    "safety reserve" input of the Runtime Context Budget (see
    `provider_manager/context_budget.py`, which computes the same
    reservation for the request actually sent to a Provider once a
    model has been selected).
    """

    warning_threshold: float = _DEFAULT_WARNING_THRESHOLD

    @property
    def usable_tokens(self) -> int:
        """
        Tokens available for context after reserving room for the
        response and the configured safety reserve.
        """

        return max(
            0,
            self.max_context_tokens
            - self.reserved_for_response
            - self.safety_reserve_tokens,
        )

    def is_over_warning_threshold(self, used_tokens: int) -> bool:
        """Whether `used_tokens` exceeds the configured warning threshold."""

        if self.max_context_tokens <= 0:
            return False

        return (used_tokens / self.max_context_tokens) >= self.warning_threshold


def load_context_engine_config(
    configuration: "Configuration | None",
) -> TokenBudget:
    """
    Load the default `TokenBudget` from the `[context_engine]`
    configuration section.
    """

    if configuration is None:
        return TokenBudget()

    return TokenBudget(
        max_context_tokens=int(
            configuration.get(
                "context_engine.default_context_window_tokens",
                _DEFAULT_MAX_CONTEXT_TOKENS,
            )
        ),
        reserved_for_response=int(
            configuration.get(
                "context_engine.reserved_for_response_tokens",
                _DEFAULT_RESERVED_FOR_RESPONSE,
            )
        ),
        safety_reserve_tokens=int(
            configuration.get(
                "context_engine.safety_reserve_tokens",
                _DEFAULT_SAFETY_RESERVE_TOKENS,
            )
        ),
        warning_threshold=float(
            configuration.get(
                "context_engine.warning_threshold",
                _DEFAULT_WARNING_THRESHOLD,
            )
        ),
    )
