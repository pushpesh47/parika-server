"""
PARIKA Core - ProviderManager Component

Defines normalized execution options for provider requests.

RequestOptions contains provider-independent execution parameters that
control how a model processes a request. These options are shared across
all ProviderRequest types and provide a consistent interface regardless
of the underlying provider.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestOptions:
    """
    Immutable execution options for provider requests.

    Attributes:
        temperature:
            Controls response randomness. None indicates the provider
            default should be used.

        max_output_tokens:
            Maximum number of output tokens to generate. None indicates
            the provider default should be used.

        top_p:
            Nucleus sampling probability. None indicates the provider
            default should be used.

        stop_sequences:
            Sequences that terminate generation early.

        stream:
            Indicates whether streaming responses are requested.

        reasoning:
            Provider-independent preference for whether the model
            should perform extended/visible reasoning ("thinking")
            before answering. `True` requests reasoning be enabled,
            `False` requests it be disabled, and `None` (the default)
            expresses no explicit preference, leaving the provider's
            own default behavior in effect.

            This field only ever carries a generic, provider-agnostic
            preference. Translating it into a concrete provider
            mechanism (e.g. Ollama's `think` request field) is the
            responsibility of the specific ProviderDriver that
            receives it; providers with no such concept simply ignore
            it.
    """

    temperature: float | None = None

    max_output_tokens: int | None = None

    top_p: float | None = None

    stop_sequences: tuple[str, ...] = ()

    stream: bool = False

    seed: int | None = None

    reasoning: bool | None = None

    context_window_tokens: int | None = None
    """
    The effective context window this request's model should be
    sized to, expressed as a plain token count. `None` (the default)
    expresses no explicit preference, leaving the provider's own
    default context window in effect.

    This is the Runtime Context Budget's `effective_context_window`
    (see `provider_manager/context_budget.py`), computed dynamically
    by Planner from the selected model's own advertised
    `ModelLimits.context_window` (Model Capabilities) narrowed by the
    `[context_engine]` configuration ceiling -- never a hardcoded
    constant.

    Like `reasoning`, this field only ever carries a generic,
    provider-independent token count. Translating it into a concrete
    provider-specific request parameter (e.g. Ollama's `num_ctx`
    request field) is the responsibility of the specific
    ProviderDriver that receives it; providers with no such concept
    simply ignore it.
    """

    estimated_prompt_tokens: int | None = None
    """
    The measured token size of this request's own complete, already
    -assembled prompt content, when one was measured. `None` (the
    default) means either no measurement was taken (e.g. a Provider
    request with no prompt concept at all, such as a future ComfyUI
    workflow or Whisper transcription request) or this
    `ProviderRequest` was built by a caller that predates this field
    -- both leave the Runtime Context Budget's sizing exactly as
    before this field existed.

    This is an *input* to the Runtime Context Budget computation
    (`provider_manager/context_budget.py
    .resolve_runtime_context_budget()`'s `required_prompt_tokens`
    argument) -- the opposite direction of `context_window_tokens`,
    which is that computation's *output*. Whoever builds the concrete
    `ProviderRequest` (AI Context Engineering's Prompt Engineering
    responsibility, e.g. `interfaces/ai_context/goal_builder.py`)
    measures its own already-fully-assembled prompt exactly once,
    using the existing `TokenEstimator` infrastructure, and sets this
    field directly at construction time -- Planner only ever reads
    it, and never computes or re-derives it itself. Like every other
    `RequestOptions` field, this carries only a generic, provider
    -independent number; no Core component ever needs to know what a
    message, a tool schema, or a prompt even is.
    """