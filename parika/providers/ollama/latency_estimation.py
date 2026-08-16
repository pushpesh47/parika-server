"""
PARIKA Ollama Provider - Baseline Latency Estimation

Derives a coarse, generic baseline latency/throughput estimate for a
discovered model from Ollama's own reported `parameter_size`
(`/api/tags`'s `details.parameter_size`, e.g. `"8.2B"`), so Planner's
`LatencyRule` (`parika/core/planner/model_selection/rules.py`) has a
provider-reported signal to compare candidates by even before any
model has actually been run.

This is intentionally coarse: it is a placeholder for the real,
observed-latency learning described as a future extension point in
`Model_Selection_Framework.md` (`enable_dynamic_latency_learning` /
`enable_dynamic_performance_learning`), not a substitute for it. It
never references a specific model name - the same formula applies to
any Ollama-compatible model, based only on the parameter count Ollama
itself reports for it.
"""

from __future__ import annotations

import re
from typing import Any

_PARAMETER_SIZE_RE = re.compile(r"([\d.]+)\s*([kKmMbBtT])?")

_UNIT_MULTIPLIERS: dict[str, float] = {
    "k": 1e3,
    "m": 1e6,
    "b": 1e9,
    "t": 1e12,
}

_MS_PER_BILLION_PARAMETERS = 60.0
"""
Coarse, generic scaling factor: estimated milliseconds of latency per
billion parameters. Chosen only to produce a *relative* ordering among
candidates (smaller models score as faster); the absolute value is
never surfaced to users and is superseded entirely once real observed
latency is available for a model.
"""

_BASE_LATENCY_MS = 200.0
"""Fixed baseline overhead (connection, scheduling) added to every estimate."""

_TOKENS_PER_SECOND_AT_ONE_BILLION_PARAMETERS = 80.0
"""Coarse baseline throughput used to derive `estimated_throughput_tps`."""

_REASONING_LATENCY_MULTIPLIER = 4.0
"""
Coarse multiplier applied to the latency estimate when Ollama itself
reports a model as supporting reasoning/"thinking" (the `"thinking"`
value in `/api/show`'s `capabilities` list - see
`model_mapping.capabilities_from_show()`). Reasoning-capable models
routinely spend several times longer per response than their raw
parameter count alone would suggest, because they generate a
(typically hidden) chain-of-thought before their visible answer. This
reflects that real, observed cost using only provider-reported
capability data - never a hardcoded model name - and exists
specifically so `LatencyRule` naturally discourages selecting a
reasoning-heavy model for requests that do not need one, matching the
"reasoning models used unnecessarily" problem this framework exists to
address.
"""


def parse_parameter_count(parameter_size: str | None) -> float | None:
    """
    Parse an Ollama `parameter_size` string (e.g. `"8.2B"`, `"70M"`)
    into an absolute parameter count.

    Returns:
        The parsed parameter count, or `None` if `parameter_size` is
        missing or unparsable.
    """

    if not parameter_size:
        return None

    match = _PARAMETER_SIZE_RE.match(parameter_size.strip())

    if not match:
        return None

    value_text, unit = match.groups()

    try:
        value = float(value_text)
    except ValueError:
        return None

    multiplier = _UNIT_MULTIPLIERS.get((unit or "").lower(), 1.0)

    return value * multiplier


def estimate_baseline_metrics(
    details: dict[str, Any],
    *,
    supports_reasoning: bool = False,
) -> dict[str, float]:
    """
    Derive a baseline `estimated_latency_ms` / `estimated_throughput_tps`
    pair from a `/api/tags` `details` object.

    Args:
        details:
            The `details` object for one model, as reported by
            `GET /api/tags`.

        supports_reasoning:
            Whether Ollama reports this model as reasoning/"thinking"
            capable (see `capabilities_from_show()`). When true, the
            latency estimate is scaled up to reflect the typical cost
            of generating a chain-of-thought before the visible
            answer.

    Returns:
        A dict with `estimated_latency_ms` and
        `estimated_throughput_tps` keys, or an empty dict when
        `parameter_size` is missing/unparsable (callers should treat
        a missing key as "unknown", not as zero).
    """

    parameter_count = parse_parameter_count(details.get("parameter_size"))

    if parameter_count is None:
        return {}

    billions = parameter_count / 1e9
    reasoning_multiplier = (
        _REASONING_LATENCY_MULTIPLIER if supports_reasoning else 1.0
    )

    return {
        "estimated_latency_ms": (
            _BASE_LATENCY_MS
            + billions * _MS_PER_BILLION_PARAMETERS * reasoning_multiplier
        ),
        "estimated_throughput_tps": (
            _TOKENS_PER_SECOND_AT_ONE_BILLION_PARAMETERS
            / max(billions, 0.1)
            / reasoning_multiplier
        ),
    }
