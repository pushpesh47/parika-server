"""
PARIKA Core - ProviderManager Component - Runtime Context Budget

Computes the dynamic, provider-independent Runtime Context Budget for
one request.

AI Context Engineering (`parika/interfaces/ai_context/`) and Brain's
`context_engine` subpackage must remain completely provider-
independent: neither one may know about Ollama, OpenAI, Anthropic,
Gemini, or any provider-specific request parameter. Instead, every
request that reaches a Provider carries a `RuntimeContextBudget`,
computed here from:

1. The selected model's own advertised capabilities
   (`ModelLimits.context_window` -- the single source of truth once a
   model has actually been selected).
2. The provider-supported context window (for providers that expose
   no separate cap beyond what the model itself reports, this is the
   same value as (1); a future Provider that discovers a narrower
   provider-side limit would supply it here too).
3. Application configuration limits (`[context_engine]
   default_context_window_tokens` in `config/defaults.toml`), acting
   as a configurable ceiling and as the fallback used whenever a
   model's own context window is unknown.
4. Reserved response tokens (`[context_engine]
   reserved_for_response_tokens`).
5. A safety reserve (`[context_engine] safety_reserve_tokens`).
6. The complete, already-fully-assembled prompt's own measured size
   (`required_prompt_tokens`, optional). AI Context Engineering's
   Prompt Engineering responsibility (`interfaces/ai_context
   /goal_builder.py`) measures the exact prompt content it just
   finished assembling -- using the same `TokenEstimator`
   infrastructure Brain's Context Budgeting already uses -- and
   carries the result on the built `ProviderRequest`'s generic
   `RequestOptions.estimated_prompt_tokens` field. When supplied,
   `effective_context_window` grows to guarantee `prompt_budget` is
   never smaller than that measured size, still never exceeding the
   selected model's own true `ModelLimits.context_window` when known.
   This is what prevents a Provider's context window from silently
   truncating prompt content that AI Context Engineering already
   decided belongs in the request (Assistant Identity, Behavior,
   Constraints, Reasoning Policy, Model Selection Policy, Worker
   Inventory, Tool Descriptions, Conversation, Memory, Knowledge --
   whichever of these actually ended up in the assembled prompt).
   `ProviderManager` never learns what any of that content is; it
   only ever receives the one already-measured token count.

This never hardcodes a context window: every value participating in
the computation is read from the selected `ProviderModel`, from
`Configuration`, or from the built `ProviderRequest`'s own measured
prompt size. The result's `effective_context_window` is what a
ProviderDriver translates into its own provider-specific context
parameter (e.g. Ollama's `num_ctx`); `prompt_budget` is what AI
Context Engineering/Context Assembly should treat as the tokens
actually available for prompt content, per
`docs/architecture/PARIKA_Decision_Flow.md` section 4.4 and
`docs/architecture/Core_Component_Responsibilities.md` sections 14
and 28.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .model_limits import ModelLimits

if TYPE_CHECKING:
    from parika.core.configuration.configuration import Configuration

_DEFAULT_MAX_CONTEXT_TOKENS: int = 8192
_DEFAULT_RESERVED_FOR_RESPONSE: int = 1024
_DEFAULT_SAFETY_RESERVE_TOKENS: int = 256


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeContextBudget:
    """
    The dynamically-computed Runtime Context Budget for one request.

    Attributes:
        effective_context_window:
            The context window this request's model should be sized
            to -- the selected model's own `context_window` (when
            known) narrowed by the configured ceiling, otherwise the
            configured ceiling alone, and then grown (never shrunk)
            to cover `required_prompt_tokens` when one was supplied
            to `resolve_runtime_context_budget()`, still never
            exceeding the selected model's own true `context_window`
            when known. This is the value a ProviderDriver translates
            into its own provider-specific context parameter.

        reserved_for_response:
            Tokens reserved for the model's own response, held back
            from the usable prompt budget.

        safety_reserve:
            Additional headroom held back from the usable prompt
            budget, on top of `reserved_for_response`, to absorb
            token-estimation error.
    """

    effective_context_window: int
    reserved_for_response: int
    safety_reserve: int

    @property
    def prompt_budget(self) -> int:
        """
        Tokens available for AI Context Engineering to spend on
        prompt content: `effective_context_window` minus both
        `reserved_for_response` and `safety_reserve`, never negative.
        """

        return max(
            0,
            self.effective_context_window
            - self.reserved_for_response
            - self.safety_reserve,
        )


def resolve_runtime_context_budget(
    model_limits: "ModelLimits | None",
    *,
    configuration: "Configuration | None",
    required_prompt_tokens: int | None = None,
) -> RuntimeContextBudget:
    """
    Compute the Runtime Context Budget for a specific selected model.

    Args:
        model_limits:
            The selected `ProviderModel.limits` (Model Capabilities),
            or `None` when no model has been selected yet. A `None`
            `ModelLimits.context_window` (a Provider that does not
            expose this information) is treated the same as
            `model_limits` itself being `None`: the configured
            ceiling is used as-is.

        configuration:
            Optional `Configuration` to read `[context_engine]`
            values from. Omitting it uses built-in defaults, exactly
            like `context_engine.load_context_engine_config()`.

        required_prompt_tokens:
            Optional measured token size of the complete, already
            -assembled prompt that will actually be sent for this
            request -- AI Context Engineering's Prompt Engineering
            responsibility supplies this (see `interfaces/ai_context
            /goal_builder.py`), via the built `ProviderRequest`'s
            `RequestOptions.estimated_prompt_tokens` field. `None`
            (the default) -- e.g. a Provider request with no prompt
            concept at all, such as a future ComfyUI/Whisper
            request -- reproduces exactly the behavior from before
            this parameter existed. When supplied and positive, the
            configured ceiling acts as a floor rather than a hard
            cap: `effective_context_window` grows just enough that
            `prompt_budget` covers `required_prompt_tokens`, still
            clamped to the selected model's own true `context_window`
            when known -- never an arbitrary buffer, never a
            hardcoded token value.

    Returns:
        The computed `RuntimeContextBudget`. Never hardcodes a
        context window: the ceiling, reserved-for-response, and
        safety-reserve values are always read from `configuration`
        (or its documented built-in defaults), and
        `required_prompt_tokens`, when supplied, is always a real
        measurement rather than a guessed constant.
    """

    config_ceiling = _read_int(
        configuration,
        "context_engine.default_context_window_tokens",
        _DEFAULT_MAX_CONTEXT_TOKENS,
    )
    reserved_for_response = _read_int(
        configuration,
        "context_engine.reserved_for_response_tokens",
        _DEFAULT_RESERVED_FOR_RESPONSE,
    )
    safety_reserve = _read_int(
        configuration,
        "context_engine.safety_reserve_tokens",
        _DEFAULT_SAFETY_RESERVE_TOKENS,
    )

    model_context_window = (
        model_limits.context_window if model_limits is not None else None
    )

    effective_context_window = (
        min(model_context_window, config_ceiling)
        if model_context_window is not None
        else config_ceiling
    )

    if required_prompt_tokens is not None and required_prompt_tokens > 0:
        required_context_window = (
            required_prompt_tokens + reserved_for_response + safety_reserve
        )
        effective_context_window = max(
            effective_context_window, required_context_window
        )

        if model_context_window is not None:
            effective_context_window = min(
                effective_context_window, model_context_window
            )

    return RuntimeContextBudget(
        effective_context_window=max(0, effective_context_window),
        reserved_for_response=max(0, reserved_for_response),
        safety_reserve=max(0, safety_reserve),
    )


def _read_int(
    configuration: "Configuration | None",
    key: str,
    default: int,
) -> int:
    """Read an integer config value, falling back to `default`."""

    if configuration is None:
        return default

    return int(configuration.get(key, default))
