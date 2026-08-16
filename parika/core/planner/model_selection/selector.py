"""
PARIKA Planner - Model Selector

Orchestrates the full selection pipeline: collect every candidate
(Provider, ProviderModel) pair, reject those failing a hard
requirement, score every remaining candidate against the registered
`ScoringRule` sequence, and deterministically pick the highest-scoring
one.

This module is Planner's own private implementation detail (imported
only from `planner.py`). It never registers anything, never executes
anything, and never talks to `ProviderManager` beyond the read-only
`Provider`/`ProviderModel` snapshots Planner already passes in -
`ProviderManager` itself is completely unaware this module exists.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from time import perf_counter
from typing import Any

from parika.core.provider_manager.context_budget import RuntimeContextBudget
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest

from .config import ModelSelectionConfig
from .evaluation import CandidateEvaluation
from .filtering import evaluate_hard_requirements
from .requirements import ExecutionRequirements, ThinkingMode
from .rules import RuleOutcome, ScoringRule
from .selection_result import ModelSelectionResult

Candidate = tuple[Provider, ProviderModel]


def apply_reasoning_preference(
    backend_request: Any,
    reasoning_enabled: bool | None,
) -> Any:
    """
    Apply a ModelSelectionResult's resolved reasoning preference onto
    a built ProviderRequest's generic `options.reasoning` field.

    This only ever sets a provider-independent preference on the
    shared `RequestOptions` type; translating it into a concrete
    provider mechanism (e.g. Ollama's `think` field) is left entirely
    to whichever ProviderDriver ultimately receives it.

    Does nothing when there is no explicit preference (AUTO), or when
    `backend_request` is not a real `ProviderRequest` (e.g. a
    caller-supplied test double), so this enhancement can never break
    a `provider_request_builder` that returns something else.
    """

    if reasoning_enabled is None or not isinstance(
        backend_request, ProviderRequest
    ):
        return backend_request

    return replace(
        backend_request,
        options=replace(backend_request.options, reasoning=reasoning_enabled),
    )


def apply_context_budget(
    backend_request: Any,
    budget: "RuntimeContextBudget | None",
) -> Any:
    """
    Apply a computed `RuntimeContextBudget` onto a built
    `ProviderRequest`'s generic `options.context_window_tokens` field.

    This only ever sets a provider-independent token count on the
    shared `RequestOptions` type (see `RequestOptions
    .context_window_tokens`'s docstring); translating it into a
    concrete provider mechanism (e.g. Ollama's `num_ctx` field) is
    left entirely to whichever ProviderDriver ultimately receives it.

    Does nothing when there is no budget to apply, or when
    `backend_request` is not a real `ProviderRequest` (e.g. a
    caller-supplied test double), so this enhancement can never break
    a `provider_request_builder` that returns something else.
    """

    if budget is None or not isinstance(backend_request, ProviderRequest):
        return backend_request

    return replace(
        backend_request,
        options=replace(
            backend_request.options,
            context_window_tokens=budget.effective_context_window,
        ),
    )


def read_estimated_prompt_tokens(backend_request: Any) -> int | None:
    """
    Read a built ProviderRequest's own `options.estimated_prompt_tokens`
    -- the complete assembled prompt's measured token size, already
    computed once by AI Context Engineering's Prompt Engineering
    responsibility (see `interfaces/ai_context/goal_builder.py`)
    before this ProviderRequest ever existed.

    This only ever reads a generic, provider-independent integer off
    the shared `RequestOptions` type; Planner never computes, or
    knows how to compute, a prompt's token size itself, and never
    inspects any provider-specific field (e.g. Ollama's `messages`/
    `tools`) to derive one.

    Returns `None` when `backend_request` is not a real
    `ProviderRequest` (e.g. a caller-supplied test double) or when no
    estimate was ever supplied (e.g. a Provider request with no
    prompt concept at all, such as a future ComfyUI/Whisper request)
    -- both cases leave `resolve_runtime_context_budget()`'s sizing
    exactly as before this field existed, matching
    `apply_reasoning_preference()`/`apply_context_budget()`'s
    identical defensive check.
    """

    if not isinstance(backend_request, ProviderRequest):
        return None

    return backend_request.options.estimated_prompt_tokens


def select_provider_model(
    *,
    providers: Sequence[Provider],
    requirements: ExecutionRequirements,
    config: ModelSelectionConfig,
    rules: Sequence[ScoringRule],
    logger: logging.Logger,
) -> ModelSelectionResult:
    """
    Select the best Provider model satisfying `requirements`.

    Args:
        providers:
            Every registered Provider (enabled or not - disabled ones
            are rejected during evaluation so they still appear in
            the returned transparency trail).

        requirements:
            The Goal's ExecutionRequirements.

        config:
            The active ModelSelectionConfig.

        rules:
            The ScoringRule sequence to evaluate every surviving
            candidate against.

        logger:
            Logger used for DEBUG-level selection transparency.

    Returns:
        The complete ModelSelectionResult. `result.succeeded` is
        False when no candidate satisfies every hard requirement;
        the caller decides how to react (Planner raises
        `NoAvailableProviderModelError`).
    """

    started_at = perf_counter()

    _log_requirements(logger, requirements)

    all_candidates: list[Candidate] = [
        (provider, model)
        for provider in providers
        for model in provider.models
    ]

    accepted: list[Candidate] = []
    evaluations: list[CandidateEvaluation] = []

    for provider, model in all_candidates:
        logger.debug(
            "Evaluating candidate: "
            "provider=%s "
            "model=%s "
            "specializations=%s "
            "modalities=%s "
            "capabilities=%s "
            "execution_features=%s",
            provider.id,
            model.id,
            sorted(model.specializations),
            sorted(model.supported_modalities),
            sorted(value.value for value in model.capabilities),
            sorted(value.value for value in model.execution_features),
        )
        rejection_reason = evaluate_hard_requirements(
            provider, model, requirements
        )

        if rejection_reason is not None:
            evaluations.append(
                CandidateEvaluation(
                    provider_id=provider.id,
                    model_id=model.id,
                    accepted=False,
                    rejection_reason=rejection_reason,
                    reason=f"rejected: {rejection_reason}",
                )
            )
        else:
            accepted.append((provider, model))

    for provider, model in accepted:
        breakdown = tuple(
            rule.evaluate(
                provider=provider,
                model=model,
                requirements=requirements,
                config=config,
                candidate_pool=accepted,
            )
            for rule in rules
        )
        total_score = sum(outcome.contribution for outcome in breakdown)

        evaluations.append(
            CandidateEvaluation(
                provider_id=provider.id,
                model_id=model.id,
                accepted=True,
                total_score=total_score,
                breakdown=breakdown,
                reason=f"scored {total_score:.2f}",
            )
        )

    evaluations.sort(key=lambda evaluation: (evaluation.provider_id, evaluation.model_id))

    _log_evaluations(logger, evaluations)

    winner = _select_best(evaluations)

    thinking_mode = config.thinking_mode_for(requirements.reasoning_level)
    reasoning_enabled = {
        ThinkingMode.OFF: False,
        ThinkingMode.ON: True,
        ThinkingMode.AUTO: None,
    }[thinking_mode]

    selected_provider = None
    selected_model = None

    if winner is not None:
        selected_provider = winner.provider_id
        selected_model = next(
            model
            for provider, model in accepted
            if provider.id == winner.provider_id and model.id == winner.model_id
        )

    result = ModelSelectionResult(
        requirements=requirements,
        selected_provider_id=selected_provider,
        selected_model=selected_model,
        thinking_mode=thinking_mode,
        reasoning_enabled=reasoning_enabled,
        total_score=winner.total_score if winner is not None else None,
        breakdown=winner.breakdown if winner is not None else (),
        reason=winner.reason if winner is not None else "no candidate satisfied every requirement",
        evaluated_candidates=tuple(evaluations),
        selection_duration_seconds=perf_counter() - started_at,
    )

    _log_selection(logger, config, result)

    return result


def _select_best(
    evaluations: Sequence[CandidateEvaluation],
) -> CandidateEvaluation | None:
    """
    Deterministically pick the highest-scoring accepted candidate.

    Ties are broken by `(provider_id, model_id)` so selection never
    depends on iteration order.
    """

    accepted = [evaluation for evaluation in evaluations if evaluation.accepted]

    if not accepted:
        return None

    return max(
        accepted,
        key=lambda evaluation: (
            evaluation.total_score,
            evaluation.provider_id,
            evaluation.model_id,
        ),
    )


def _log_requirements(
    logger: logging.Logger,
    requirements: ExecutionRequirements,
) -> None:
    logger.debug(
        "Model selection requirements: capability=%s reasoning_level=%s "
        "tool_calling=%s information_freshness=%s capability_hints=%s "
        "streaming_required=%s min_context_window=%s",
        requirements.capability.value,
        requirements.reasoning_level.value,
        requirements.tool_calling.value,
        requirements.information_freshness.value,
        [hint.value for hint in requirements.capability_hints],
        requirements.streaming_required,
        requirements.min_context_window,
    )


def _log_evaluations(
    logger: logging.Logger,
    evaluations: Sequence[CandidateEvaluation],
) -> None:
    for evaluation in evaluations:
        if not evaluation.accepted:
            logger.debug(
                "Candidate provider=%s model=%s rejected: %s",
                evaluation.provider_id,
                evaluation.model_id,
                evaluation.rejection_reason,
            )
            continue

        breakdown_text = ", ".join(
            f"{outcome.rule_id}={outcome.contribution:.2f}"
            for outcome in evaluation.breakdown
        )
        logger.debug(
            "Candidate provider=%s model=%s score=%.2f breakdown=[%s]",
            evaluation.provider_id,
            evaluation.model_id,
            evaluation.total_score,
            breakdown_text,
        )


def _log_selection(
    logger: logging.Logger,
    config: ModelSelectionConfig,
    result: ModelSelectionResult,
) -> None:
    if not config.log_decision:
        return

    if not result.succeeded:
        logger.debug(
            "Model selection failed: %s (evaluated %d candidate(s)).",
            result.reason,
            len(result.evaluated_candidates),
        )
        return

    logger.debug(
        "Selected provider=%s model=%s score=%.2f thinking_mode=%s "
        "reasoning_enabled=%s selection_time_ms=%.3f",
        result.selected_provider_id,
        result.selected_model.id if result.selected_model else None,
        result.total_score,
        result.thinking_mode.value,
        result.reasoning_enabled,
        result.selection_duration_seconds * 1000,
    )
