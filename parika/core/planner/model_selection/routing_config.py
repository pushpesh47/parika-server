"""
PARIKA Planner - Routing Model Selection Configuration

Reads the `[routing_model]` TOML section through the existing
`Configuration` Core component and exposes it as a small, typed,
read-only snapshot - the exact same pattern `model_selection/config
.py` already establishes for `[model_selection]`.

`[routing_model]` controls only *how Planner selects the routing
model* (see `parika.core.planner.goal.ROUTING_GOAL_METADATA_KEY` and
`docs/architecture/Model_Selection_Framework.md` §14): whether it
keeps scoring every candidate through the unmodified Model Selection
Framework (`mode = "auto"`, the default, identical to today's
behavior), or skips scoring entirely and uses one pinned, operator-
configured model instead (`mode = "fixed"`). Worker model selection
(every other Goal) never reads this section at all - it always
continues to call `selector.select_provider_model()` directly.

This is a thin wrapper, not a parallel configuration system:
`Configuration` remains the single source of truth. Every value here
falls back to a safe default - including an unrecognized `mode`
string, which is treated exactly like `"auto"` - so a missing or
partially-configured `[routing_model]` section, or no `Configuration`
at all, always preserves today's behavior unchanged.

For backward compatibility, the legacy `[planner.routing]` namespace
is still read as a fallback when `[routing_model]` does not define a
given key. `[routing_model]` always takes precedence when both are
present.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

VALID_ROUTING_MODES: frozenset[str] = frozenset({"auto", "fixed"})
"""The only recognized `[routing_model] mode` values."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RoutingConfig:
    """
    Immutable, typed snapshot of `[routing_model]` configuration.
    """

    mode: str = "auto"
    """
    `"auto"` (default): Planner selects the routing model exactly as
    it always has, through the unmodified Model Selection Framework
    scoring pipeline.

    `"fixed"`: Planner uses `fixed_model`/`fixed_thinking` directly
    for the routing Goal, bypassing scoring for it. Any other, unknown
    value is treated as `"auto"`.
    """

    fixed_provider_id: str | None = None
    """
    Optional Provider id to disambiguate `fixed_model_id` when more
    than one registered Provider could expose a model with that id.
    `None` (the default) matches the first registered Provider (sorted
    by id) exposing a model with `fixed_model_id`.
    """

    fixed_model_id: str = ""
    """
    The routing model's id to use when `mode = "fixed"`. Empty (the
    default) is treated as "not configured", which - exactly like a
    configured model that turns out to be unavailable - causes Planner
    to log a warning and fall back to `"auto"` for that request.
    """

    fixed_thinking: bool = False

    routing_type: str = "local"
    """
    The routing type: "local" or "cloud". When "cloud", the fixed
    three-slot chain (primary → secondary → fallback) is used.
    """

    @property
    def is_fixed(self) -> bool:
        """Whether the "fixed" routing strategy is active."""

        return self.mode == "fixed"

    @property
    def cloud_primary_provider(self) -> str:
        """The fixed primary cloud provider slot name."""
        return "primary"

    @property
    def cloud_secondary_provider(self) -> str:
        """The fixed secondary cloud provider slot name."""
        return "secondary"

    @property
    def cloud_fallback_provider(self) -> str:
        """The fixed fallback cloud provider slot name."""
        return "fallback"


def load_routing_config(
    configuration: Configuration | None,
) -> RoutingConfig:
    """
    Build a `RoutingConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default (`mode = "auto"`),
            so Planner remains fully functional and behaves exactly as
            it did before `[routing_model]` existed.

    Returns:
        The resolved, immutable configuration snapshot.
    """

    if configuration is None:
        return RoutingConfig()

    mode = _get_with_legacy_fallback(configuration, "mode", "auto")

    if not isinstance(mode, str) or mode not in VALID_ROUTING_MODES:
        mode = "auto"

    provider_id, model_id = _parse_fixed_model(
        _get_with_legacy_fallback(configuration, "fixed_model", "")
    )

    fixed_thinking = bool(
        _get_with_legacy_fallback(configuration, "fixed_thinking", False)
    )

    routing_type = str(configuration.get("routing.type", "local")).lower()

    return RoutingConfig(
        mode=mode,
        fixed_provider_id=provider_id,
        fixed_model_id=model_id,
        fixed_thinking=fixed_thinking,
        routing_type=routing_type,
    )


_NOT_SET = object()
"""Sentinel distinguishing "key absent" from a legitimately falsy value."""


def _get_with_legacy_fallback(
    configuration: Configuration,
    key: str,
    default: object,
) -> object:
    """
    Read `routing_model.{key}`, falling back to the legacy
    `planner.routing.{key}` namespace only when `routing_model` does
    not define that key.

    `[routing_model]` always takes precedence over the deprecated
    `[planner.routing]` alias when both are present. Uses a sentinel
    default (rather than `Configuration.has()`) so this only requires
    the same minimal `.get()` interface every other caller already
    relies on.
    """

    value = configuration.get(f"routing_model.{key}", _NOT_SET)

    if value is not _NOT_SET:
        return value

    return configuration.get(f"planner.routing.{key}", default)


def _parse_fixed_model(raw: object) -> tuple[str | None, str]:
    """
    Parse `[routing_model] fixed_model` into an optional Provider id
    and a model id.

    Accepts either a bare model id (`"qwen3:8b"`, matched against any
    registered Provider) or a `"provider_id/model_id"` pair (e.g.
    `"provider.ollama/qwen3:8b"`) to disambiguate when more than one
    Provider could expose a model with that id - the same
    `"{provider.id}/{model.id}"` convention already used by
    `interfaces/ai_context/worker_inventory.py`. A non-string or empty
    value yields `(None, "")`, i.e. "not configured".
    """

    if not isinstance(raw, str) or not raw:
        return None, ""

    if "/" in raw:
        provider_id, _, model_id = raw.partition("/")
        return (provider_id or None), model_id

    return None, raw
