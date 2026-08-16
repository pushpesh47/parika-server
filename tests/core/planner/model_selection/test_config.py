"""
Unit tests for `parika.core.planner.model_selection.config`.

Verifies that configuration is read exclusively through the Core
`Configuration` component (never a parallel source), with sensible
defaults when a section - or `Configuration` itself - is absent.
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.core.planner.model_selection.config import (
    DEFAULT_PREFERENCES,
    DEFAULT_WEIGHTS,
    load_model_selection_config,
)
from parika.core.planner.model_selection.requirements import (
    ReasoningLevel,
    ThinkingMode,
)


class TestLoadModelSelectionConfigWithoutConfiguration:
    def test_none_configuration_uses_built_in_defaults(self) -> None:
        config = load_model_selection_config(None)

        assert config.weight_for("latency") == DEFAULT_WEIGHTS["latency"]
        assert config.prefers("prefer_local") is True
        assert (
            config.thinking_mode_for(ReasoningLevel.SIMPLE)
            is ThinkingMode.OFF
        )

    def test_unloaded_configuration_uses_built_in_defaults(self) -> None:
        config = load_model_selection_config(Configuration())

        assert config.weights == DEFAULT_WEIGHTS or dict(
            config.weights
        ) == dict(DEFAULT_WEIGHTS)
        assert config.log_decision is True


class TestModelSelectionConfigFallbacks:
    def test_weight_for_unknown_rule_id_is_zero(self) -> None:
        config = load_model_selection_config(None)

        assert config.weight_for("some_future_dimension") == 0.0

    def test_prefers_unknown_preference_is_false(self) -> None:
        config = load_model_selection_config(None)

        assert config.prefers("some_future_preference") is False

    def test_thinking_mode_for_unmapped_level_defaults_to_auto(self) -> None:
        config = load_model_selection_config(None)

        assert (
            config.thinking_mode_for(ReasoningLevel.NORMAL)
            is ThinkingMode.AUTO
        )


class _FakeConfiguration:
    """
    Minimal Configuration stand-in exposing only `.get()`, used to
    verify override-merging behavior deterministically without
    depending on real TOML files on disk.
    """

    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


class TestLoadModelSelectionConfigOverrides:
    def test_configured_weight_overrides_default(self) -> None:
        configuration = _FakeConfiguration(
            {"model_selection.weights": {"latency": 99}}
        )

        config = load_model_selection_config(configuration)  # type: ignore[arg-type]

        assert config.weight_for("latency") == 99.0
        # Unconfigured weights still fall back to their defaults.
        assert config.weight_for("reasoning") == DEFAULT_WEIGHTS["reasoning"]

    def test_configured_preference_overrides_default(self) -> None:
        configuration = _FakeConfiguration(
            {"model_selection.preferences": {"prefer_local": False}}
        )

        config = load_model_selection_config(configuration)  # type: ignore[arg-type]

        assert config.prefers("prefer_local") is False
        assert config.prefers("prefer_streaming") is True

    def test_configured_reasoning_mode_overrides_default(self) -> None:
        configuration = _FakeConfiguration(
            {"model_selection.reasoning": {"normal": "off"}}
        )

        config = load_model_selection_config(configuration)  # type: ignore[arg-type]

        assert (
            config.thinking_mode_for(ReasoningLevel.NORMAL)
            is ThinkingMode.OFF
        )
        assert (
            config.thinking_mode_for(ReasoningLevel.COMPLEX)
            is ThinkingMode.ON
        )

    def test_invalid_reasoning_mode_entry_is_ignored(self) -> None:
        configuration = _FakeConfiguration(
            {
                "model_selection.reasoning": {
                    "normal": "not-a-real-mode",
                    "bogus_level": "on",
                }
            }
        )

        config = load_model_selection_config(configuration)  # type: ignore[arg-type]

        assert (
            config.thinking_mode_for(ReasoningLevel.NORMAL)
            is ThinkingMode.AUTO
        )

    def test_scalar_flags_are_read_through_configuration(self) -> None:
        configuration = _FakeConfiguration(
            {"model_selection.log_decision": False}
        )

        config = load_model_selection_config(configuration)  # type: ignore[arg-type]

        assert config.log_decision is False


class TestDefaultConstantsMatchDocumentedExample:
    def test_default_weights_sum_matches_documented_example(self) -> None:
        assert DEFAULT_WEIGHTS == {
            "latency": 40.0,
            "reasoning": 25.0,
            "tool_calling": 20.0,
            "context_window": 10.0,
            "cost": 5.0,
            "routing_recommendation": 20.0,
        }

    def test_default_preferences_match_documented_example(self) -> None:
        assert dict(DEFAULT_PREFERENCES) == {
            "prefer_local": True,
            "prefer_streaming": True,
            "prefer_healthier_provider": True,
            "prefer_lower_latency": True,
            "prefer_larger_context": False,
        }
