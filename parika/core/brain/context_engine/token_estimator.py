"""
PARIKA Brain - Context Engine - Token Estimator

Defines the `TokenEstimator` Protocol and a stdlib-only default
implementation, following the exact pluggable-Protocol shape already
used for `ScoringRule`/`ExperienceSource`.

See docs/architecture/Intelligence_Foundation_Design.md section 7.2.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

_CHARS_PER_TOKEN_HEURISTIC: int = 4


@runtime_checkable
class TokenEstimator(Protocol):
    """Structural contract for estimating a text's token count."""

    def estimate(self, text: str) -> int:
        """Return an estimated token count for `text`."""


class HeuristicTokenEstimator:
    """
    Default, stdlib-only, zero-dependency token estimator.

    Uses a coarse `len(text) // 4` heuristic -- documented as
    approximate, not exact. A future, more accurate provider-specific
    tokenizer can be substituted via the `TokenEstimator` Protocol
    without any redesign (see the design document's note on preferring
    a Provider's own reported usage, e.g. Ollama's `eval_count`, to
    refine future estimates once available).
    """

    def estimate(self, text: str) -> int:
        if not text:
            return 0

        return max(1, len(text) // _CHARS_PER_TOKEN_HEURISTIC)
