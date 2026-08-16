"""
PARIKA Planner - Model Selection Configuration

Reads the `[model_selection]` TOML section through the existing
`Configuration` Core component and exposes it as a small, typed,
read-only snapshot.

This module is a thin wrapper, not a parallel configuration system:
`Configuration` remains the single source of truth for every value
here. `load_model_selection_config()` performs nothing but
`Configuration.get()` calls, merged over built-in defaults so
selection behaves sensibly even when a section (or all of
`[model_selection]`) is absent - which is also why every built-in
`ScoringRule` and the reasoning-mode mapping still work correctly when
Planner is constructed without a `Configuration` at all (`None`),
exactly preserving today's behavior for existing callers/tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from parika.core.configuration.configuration import Configuration

from .requirements import ReasoningLevel, ThinkingMode

DEFAULT_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "latency": 40.0,
        "reasoning": 25.0,
        "tool_calling": 20.0,
        "context_window": 10.0,
        "cost": 5.0,
        "routing_recommendation": 20.0,
    }
)
"""
Fallback weights used for any weight key not present in
`[model_selection.weights]`, and for every weight when
`Configuration` is not supplied at all. Adding a brand new scoring
dimension never requires editing this table: a rule with no matching
configured *and* no matching default weight simply contributes 0.
"""

DEFAULT_PREFERENCES: Mapping[str, bool] = MappingProxyType(
    {
        "prefer_local": True,
        "prefer_streaming": True,
        "prefer_healthier_provider": True,
        "prefer_lower_latency": True,
        "prefer_larger_context": False,
    }
)

DEFAULT_REASONING_MODES: Mapping[ReasoningLevel, ThinkingMode] = MappingProxyType(
    {
        ReasoningLevel.SIMPLE: ThinkingMode.OFF,
        ReasoningLevel.NORMAL: ThinkingMode.AUTO,
        ReasoningLevel.COMPLEX: ThinkingMode.ON,
    }
)

_PREFERENCE_BONUS_MAGNITUDE = 5.0
"""
Fixed bonus magnitude added by a satisfied boolean preference. Kept
on the same rough scale as the example weight table (which sums to
100) so a single satisfied preference behaves like a small, sensible
nudge rather than dominating the weighted score.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelSelectionConfig:
    """
    Immutable, typed snapshot of `[model_selection]` configuration.
    """

    default_strategy: str = "weighted"
    fallback_strategy: str = "highest_score"
    allow_provider_fallback: bool = True
    allow_model_fallback: bool = True
    enable_dynamic_latency_learning: bool = True
    enable_dynamic_performance_learning: bool = True
    log_decision: bool = True

    weights: Mapping[str, float] = field(
        default_factory=lambda: DEFAULT_WEIGHTS
    )
    preferences: Mapping[str, bool] = field(
        default_factory=lambda: DEFAULT_PREFERENCES
    )
    reasoning_modes: Mapping[ReasoningLevel, ThinkingMode] = field(
        default_factory=lambda: DEFAULT_REASONING_MODES
    )
    preference_bonus_magnitude: float = _PREFERENCE_BONUS_MAGNITUDE

    def weight_for(self, rule_id: str) -> float:
        """
        Return the configured weight for a scoring rule id, falling
        back to the built-in default weight, then to 0.0.
        """

        if rule_id in self.weights:
            return float(self.weights[rule_id])

        return float(DEFAULT_WEIGHTS.get(rule_id, 0.0))

    def prefers(self, preference_id: str) -> bool:
        """
        Return whether a boolean preference is enabled, falling back
        to its built-in default, then to False.
        """

        if preference_id in self.preferences:
            return bool(self.preferences[preference_id])

        return bool(DEFAULT_PREFERENCES.get(preference_id, False))

    def thinking_mode_for(self, reasoning_level: ReasoningLevel) -> ThinkingMode:
        """
        Return the configured `ThinkingMode` for a `ReasoningLevel`,
        falling back to the built-in default mapping, then to AUTO.
        """

        if reasoning_level in self.reasoning_modes:
            return self.reasoning_modes[reasoning_level]

        return DEFAULT_REASONING_MODES.get(reasoning_level, ThinkingMode.AUTO)


def load_model_selection_config(
    configuration: Configuration | None,
) -> ModelSelectionConfig:
    """
    Build a `ModelSelectionConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default, so Planner
            remains fully functional (matching today's behavior)
            without requiring every caller to supply a Configuration.

    Returns:
        The resolved, immutable configuration snapshot.
    """

    if configuration is None:
        return ModelSelectionConfig()

    weights = _merge(
        DEFAULT_WEIGHTS,
        configuration.get("model_selection.weights", {}),
    )
    preferences = _merge(
        DEFAULT_PREFERENCES,
        configuration.get("model_selection.preferences", {}),
    )
    reasoning_modes = _load_reasoning_modes(configuration)

    return ModelSelectionConfig(
        default_strategy=configuration.get(
            "model_selection.default_strategy", "weighted"
        ),
        fallback_strategy=configuration.get(
            "model_selection.fallback_strategy", "highest_score"
        ),
        allow_provider_fallback=bool(
            configuration.get("model_selection.allow_provider_fallback", True)
        ),
        allow_model_fallback=bool(
            configuration.get("model_selection.allow_model_fallback", True)
        ),
        enable_dynamic_latency_learning=bool(
            configuration.get(
                "model_selection.enable_dynamic_latency_learning", True
            )
        ),
        enable_dynamic_performance_learning=bool(
            configuration.get(
                "model_selection.enable_dynamic_performance_learning", True
            )
        ),
        log_decision=bool(
            configuration.get("model_selection.log_decision", True)
        ),
        weights=weights,
        preferences=preferences,
        reasoning_modes=reasoning_modes,
    )


def _merge(defaults: Mapping[str, Any], overrides: Any) -> Mapping[str, Any]:
    """
    Merge configured overrides over a built-in default mapping.
    """

    merged = dict(defaults)

    if isinstance(overrides, Mapping):
        merged.update(overrides)

    return MappingProxyType(merged)


def _load_reasoning_modes(
    configuration: Configuration,
) -> Mapping[ReasoningLevel, ThinkingMode]:
    """
    Load and parse `[model_selection.reasoning]` into a
    `ReasoningLevel -> ThinkingMode` mapping.
    """

    raw = configuration.get("model_selection.reasoning", {})

    if not isinstance(raw, Mapping):
        return DEFAULT_REASONING_MODES

    parsed: dict[ReasoningLevel, ThinkingMode] = dict(DEFAULT_REASONING_MODES)

    for level_name, mode_name in raw.items():
        try:
            level = ReasoningLevel(level_name)
            mode = ThinkingMode(mode_name)
        except ValueError:
            continue

        parsed[level] = mode

    return MappingProxyType(parsed)
