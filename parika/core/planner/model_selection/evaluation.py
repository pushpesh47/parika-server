"""
PARIKA Planner - Candidate Evaluation

Defines `CandidateEvaluation`: the complete record of how a single
(Provider, ProviderModel) candidate fared during selection - whether
it was rejected outright by a hard requirement, or scored by every
registered `ScoringRule`.

Every candidate Planner considers gets a `CandidateEvaluation`, not
just the winner, so `ModelSelectionResult.evaluated_candidates` can
answer "why wasn't model X chosen?" directly from logs/diagnostics
without needing to reproduce the selection run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rules import RuleOutcome


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateEvaluation:
    """
    Immutable evaluation record for a single candidate.
    """

    provider_id: str
    model_id: str

    accepted: bool
    """
    Whether this candidate survived hard-requirement filtering and was
    actually scored. Rejected candidates always have `total_score`
    0.0 and an empty `breakdown`.
    """

    total_score: float = 0.0
    """Sum of every RuleOutcome's `contribution`, for accepted candidates."""

    breakdown: tuple[RuleOutcome, ...] = field(default_factory=tuple)
    """Per-rule outcomes, for accepted candidates."""

    rejection_reason: str | None = None
    """Why this candidate was rejected, when `accepted` is False."""

    reason: str = ""
    """Short, human-readable summary of this evaluation's outcome."""
