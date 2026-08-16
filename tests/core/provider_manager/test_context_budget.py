"""
Unit tests for `parika.core.provider_manager.context_budget`.
"""

from __future__ import annotations

from parika.core.provider_manager.context_budget import (
    RuntimeContextBudget,
    resolve_runtime_context_budget,
)
from parika.core.provider_manager.model_limits import ModelLimits


class _FakeConfiguration:
    """
    Minimal Configuration stand-in exposing only `.get()`, following
    the same pattern as
    `tests/core/planner/model_selection/test_config.py`.
    """

    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


class TestRuntimeContextBudgetPromptBudget:
    def test_prompt_budget_subtracts_reservations(self) -> None:
        budget = RuntimeContextBudget(
            effective_context_window=10000,
            reserved_for_response=1000,
            safety_reserve=200,
        )

        assert budget.prompt_budget == 8800

    def test_prompt_budget_never_negative(self) -> None:
        budget = RuntimeContextBudget(
            effective_context_window=100,
            reserved_for_response=500,
            safety_reserve=500,
        )

        assert budget.prompt_budget == 0


class TestResolveRuntimeContextBudgetNoConfiguration:
    def test_none_configuration_uses_built_in_defaults(self) -> None:
        budget = resolve_runtime_context_budget(None, configuration=None)

        assert budget.effective_context_window == 8192
        assert budget.reserved_for_response == 1024
        assert budget.safety_reserve == 256

    def test_none_model_limits_falls_back_to_config_ceiling(self) -> None:
        budget = resolve_runtime_context_budget(None, configuration=None)

        assert budget.effective_context_window == 8192

    def test_model_limits_with_no_context_window_falls_back_to_ceiling(
        self,
    ) -> None:
        budget = resolve_runtime_context_budget(
            ModelLimits(context_window=None), configuration=None
        )

        assert budget.effective_context_window == 8192


class TestResolveRuntimeContextBudgetModelCapabilities:
    def test_smaller_model_window_narrows_below_config_ceiling(self) -> None:
        """
        A model whose own context window is smaller than the
        configured ceiling must never be inflated up to that ceiling.
        """

        budget = resolve_runtime_context_budget(
            ModelLimits(context_window=4096), configuration=None
        )

        assert budget.effective_context_window == 4096

    def test_larger_model_window_is_capped_by_config_ceiling(self) -> None:
        """
        A model whose own context window exceeds the configured
        ceiling is capped by it -- the configured ceiling is a real
        application limit, not merely a fallback default.
        """

        budget = resolve_runtime_context_budget(
            ModelLimits(context_window=128000), configuration=None
        )

        assert budget.effective_context_window == 8192


class TestResolveRuntimeContextBudgetFromConfiguration:
    def test_reads_configured_ceiling_reserve_and_safety_reserve(
        self,
    ) -> None:
        configuration = _FakeConfiguration(
            {
                "context_engine.default_context_window_tokens": 40960,
                "context_engine.reserved_for_response_tokens": 2048,
                "context_engine.safety_reserve_tokens": 512,
            }
        )

        budget = resolve_runtime_context_budget(
            ModelLimits(context_window=40960),
            configuration=configuration,  # type: ignore[arg-type]
        )

        assert budget.effective_context_window == 40960
        assert budget.reserved_for_response == 2048
        assert budget.safety_reserve == 512
        assert budget.prompt_budget == 40960 - 2048 - 512

    def test_model_window_still_narrows_a_larger_configured_ceiling(
        self,
    ) -> None:
        configuration = _FakeConfiguration(
            {"context_engine.default_context_window_tokens": 128000}
        )

        budget = resolve_runtime_context_budget(
            ModelLimits(context_window=8192),
            configuration=configuration,  # type: ignore[arg-type]
        )

        assert budget.effective_context_window == 8192


class TestResolveRuntimeContextBudgetNeverHardcoded:
    def test_different_models_yield_different_effective_windows(self) -> None:
        """
        The same call site must yield a different effective context
        window for different selected models -- the defining property
        of a dynamically-computed, non-hardcoded Runtime Context
        Budget.
        """

        small = resolve_runtime_context_budget(
            ModelLimits(context_window=2048), configuration=None
        )
        large = resolve_runtime_context_budget(
            ModelLimits(context_window=8192), configuration=None
        )

        assert small.effective_context_window == 2048
        assert large.effective_context_window == 8192
        assert small.effective_context_window != large.effective_context_window


class TestResolveRuntimeContextBudgetRequiredPromptTokens:
    """
    Coverage for `required_prompt_tokens` -- the complete assembled
    prompt's own measured size, supplied by AI Context Engineering's
    Prompt Engineering responsibility (see `interfaces/ai_context
    /goal_builder.py`) via `RequestOptions.estimated_prompt_tokens`.
    """

    def test_omitted_reproduces_existing_behavior(self) -> None:
        omitted = resolve_runtime_context_budget(
            ModelLimits(context_window=4096), configuration=None
        )
        explicit_none = resolve_runtime_context_budget(
            ModelLimits(context_window=4096),
            configuration=None,
            required_prompt_tokens=None,
        )

        assert omitted.effective_context_window == 4096
        assert explicit_none.effective_context_window == 4096

    def test_zero_or_negative_reproduces_existing_behavior(self) -> None:
        zero = resolve_runtime_context_budget(
            ModelLimits(context_window=4096),
            configuration=None,
            required_prompt_tokens=0,
        )
        negative = resolve_runtime_context_budget(
            ModelLimits(context_window=4096),
            configuration=None,
            required_prompt_tokens=-500,
        )

        assert zero.effective_context_window == 4096
        assert negative.effective_context_window == 4096

    def test_grows_effective_window_beyond_the_config_ceiling(self) -> None:
        """
        The reported num_ctx issue: a prompt larger than the default
        ceiling (identity + behavior + tool schemas + worker
        inventory, etc.) must not be silently truncated -- the
        ceiling becomes a floor, not a hard cap, once the real prompt
        size is known.
        """

        configuration = _FakeConfiguration(
            {
                "context_engine.default_context_window_tokens": 8192,
                "context_engine.reserved_for_response_tokens": 1024,
                "context_engine.safety_reserve_tokens": 256,
            }
        )

        budget = resolve_runtime_context_budget(
            ModelLimits(context_window=None),
            configuration=configuration,  # type: ignore[arg-type]
            required_prompt_tokens=11087,
        )

        assert budget.effective_context_window == 11087 + 1024 + 256
        assert budget.prompt_budget >= 11087

    def test_clamped_to_the_selected_models_own_context_window(self) -> None:
        """
        A prompt that is too large even for the selected model's own
        advertised context window can never be sized beyond that
        model's real, physical limit -- growing `num_ctx` past what
        the model actually supports is not a valid remediation.
        """

        budget = resolve_runtime_context_budget(
            ModelLimits(context_window=4096),
            configuration=None,
            required_prompt_tokens=50000,
        )

        assert budget.effective_context_window == 4096

    def test_small_required_prompt_tokens_never_shrinks_the_window(self) -> None:
        without_requirement = resolve_runtime_context_budget(
            ModelLimits(context_window=40960), configuration=None
        )
        with_small_requirement = resolve_runtime_context_budget(
            ModelLimits(context_window=40960),
            configuration=None,
            required_prompt_tokens=10,
        )

        assert (
            with_small_requirement.effective_context_window
            == without_requirement.effective_context_window
        )

    def test_never_uses_an_arbitrary_fixed_buffer(self) -> None:
        """
        The grown window tracks the measured requirement exactly
        (plus the already-configured, non-arbitrary reserved-for
        -response/safety-reserve amounts) -- never a fixed, guessed
        margin such as the previously-observed `+1000` workaround.
        """

        smaller = resolve_runtime_context_budget(
            ModelLimits(context_window=None),
            configuration=None,
            required_prompt_tokens=9000,
        )
        larger = resolve_runtime_context_budget(
            ModelLimits(context_window=None),
            configuration=None,
            required_prompt_tokens=20000,
        )

        assert larger.effective_context_window - smaller.effective_context_window == (
            20000 - 9000
        )
