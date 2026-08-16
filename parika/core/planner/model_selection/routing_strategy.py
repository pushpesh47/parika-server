"""
PARIKA Planner - Fixed Routing Model Selection

Implements the "fixed" routing strategy (`[routing_model]
mode = "fixed"`, see `routing_config.py` and `docs/architecture
/Model_Selection_Framework.md` §14): Planner uses
`select_fixed_routing_model()` to resolve the operator-pinned routing
model directly, instead of scoring every candidate through
`selector.select_provider_model()`.

This never introduces a second selection pipeline or duplicates
selection logic:

- Candidate discovery still reads `Provider`/`ProviderModel` snapshots
  the caller already obtained from `ProviderManager.get_all()` -
  exactly like `selector.select_provider_model()` does.
- Hard-requirement compatibility (capability, specializations,
  modalities, provider health/availability, context window,
  resources) is still checked through the exact same, unmodified
  `filtering.evaluate_hard_requirements()` every candidate is
  evaluated against in the "auto" strategy.
- Only the *scoring* step (`rules.py`/`preference_rules.py`,
  `selector._select_best()`) is skipped, because the operator has
  already made that choice explicit.
- The result is the same `ModelSelectionResult` type
  `select_provider_model()` returns, so Planner's caller-facing
  contract (`selection.succeeded`, `.selected_model`,
  `.selected_provider_id`, `.reasoning_enabled`, ...) never changes.

Availability failures (not configured, not registered, or rejected by
the hard-requirement pipeline) never raise: `select_fixed_routing_model()`
returns `None` and logs a WARNING describing why, so Planner can
transparently fall back to `selector.select_provider_model()` (the
"auto" strategy) for that one decision - `[routing_model]`'s
required "never crash, fall back to auto" contract.

This module is Planner's own private implementation detail, imported
only from `planner.py`, exactly like `selector.py`. Worker model
selection never imports or calls anything here - it always calls
`selector.select_provider_model()` directly.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel

from .filtering import evaluate_hard_requirements
from .requirements import ExecutionRequirements, ThinkingMode
from .routing_config import RoutingConfig
from .selection_result import ModelSelectionResult

Candidate = tuple[Provider, ProviderModel]


def select_fixed_routing_model(
    *,
    providers: Sequence[Provider],
    requirements: ExecutionRequirements,
    routing_config: RoutingConfig,
    logger: logging.Logger,
) -> ModelSelectionResult | None:
    """
    Resolve `routing_config`'s pinned routing model directly.

    Args:
        providers:
            Every registered Provider, exactly as
            `selector.select_provider_model()` receives them.

        requirements:
            The routing Goal's `ExecutionRequirements`, used only to
            run the pinned candidate through the unmodified hard-
            requirement filtering pipeline - never to score it.

        routing_config:
            The active `RoutingConfig`. Only ever called by Planner
            when `routing_config.mode == "fixed"`.

        logger:
            Logger used for the required fallback WARNING and DEBUG-
            level selection transparency, matching `selector.py`'s
            own conventions.

    Returns:
        A `ModelSelectionResult` selecting the configured model when
        it is registered, enabled, healthy, and satisfies every hard
        requirement - or `None` when it cannot be used for any
        reason, in which case a WARNING has already been logged and
        the caller is expected to fall back to
        `selector.select_provider_model()` for this decision.
    """

    if not routing_config.fixed_model_id:
        logger.warning(
            "[routing_model] mode is 'fixed' but no fixed_model is "
            "configured; falling back to automatic routing model "
            "selection for this request."
        )
        return None

    candidate = _find_candidate(providers, routing_config)

    if candidate is None:
        logger.warning(
            "Configured fixed routing model '%s' is not registered "
            "with any Provider (not installed, or its Provider is "
            "offline); falling back to automatic routing model "
            "selection for this request.",
            _describe(routing_config),
        )
        return None

    provider, model = candidate

    rejection_reason = evaluate_hard_requirements(provider, model, requirements)

    if rejection_reason is not None:
        logger.warning(
            "Configured fixed routing model '%s/%s' is unavailable "
            "(%s); falling back to automatic routing model selection "
            "for this request.",
            provider.id,
            model.id,
            rejection_reason,
        )
        return None

    reasoning_enabled = bool(routing_config.fixed_thinking)
    thinking_mode = ThinkingMode.ON if reasoning_enabled else ThinkingMode.OFF

    logger.debug(
        "Using fixed routing model: provider=%s model=%s "
        "fixed_thinking=%s.",
        provider.id,
        model.id,
        reasoning_enabled,
    )

    return ModelSelectionResult(
        requirements=requirements,
        selected_provider_id=provider.id,
        selected_model=model,
        thinking_mode=thinking_mode,
        reasoning_enabled=reasoning_enabled,
        total_score=None,
        breakdown=(),
        reason=(
            "fixed routing model configured via "
            f"[routing_model] fixed_model='{provider.id}/{model.id}'"
        ),
        evaluated_candidates=(),
    )


def _find_candidate(
    providers: Sequence[Provider],
    routing_config: RoutingConfig,
) -> Candidate | None:
    """
    Find the first registered `(Provider, ProviderModel)` pair whose
    model id matches `routing_config.fixed_model_id`, optionally
    narrowed to `routing_config.fixed_provider_id`.

    Iterates in a deterministic order (`(provider.id, model.id)`,
    matching `selector.py`'s own tie-break convention) so the outcome
    never depends on `ProviderManager.get_all()`'s iteration order.
    """

    for provider in sorted(providers, key=lambda provider: provider.id):
        if (
            routing_config.fixed_provider_id is not None
            and provider.id != routing_config.fixed_provider_id
        ):
            continue

        for model in sorted(provider.models, key=lambda model: model.id):
            if model.id == routing_config.fixed_model_id:
                return provider, model

    return None


def _describe(routing_config: RoutingConfig) -> str:
    """Human-readable description of the configured fixed model."""

    if routing_config.fixed_provider_id is not None:
        return f"{routing_config.fixed_provider_id}/{routing_config.fixed_model_id}"

    return routing_config.fixed_model_id
