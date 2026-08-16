"""
PARIKA Planner - Experience Source Protocol

Defines the narrow, structurally-typed contract Planner depends on to
read a derived "historical success rate" signal for `ExperienceRule`
(rules.py).

This Protocol is owned by Planner's own package -- exactly like
`ScoringRule` is an ABC owned by its consuming
packages -- so Planner's source code never imports a concrete
implementation. The concrete implementation (`ExperienceStore`) lives
in a Module (`parika/modules/experience/`) and is injected at the
composition root (`parika/interfaces/runtime.py`).

See docs/architecture/Intelligence_Foundation_Design.md section 6A for
the full rationale: this keeps the frozen 29-item Core component list
completely unchanged while still letting Planner's scoring pipeline
consult Experience data, using the same dependency-inversion pattern
already used throughout this codebase (`KnowledgeEngine`/
`KnowledgeStorage` ABCs defined in Core, concrete implementations
living outside it).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExperienceSource(Protocol):
    """
    Structural contract for reading aggregated Experience data.

    Any object exposing this one method satisfies the Protocol --
    Planner never imports or names a concrete implementing class.
    """

    def aggregate_outcome_rate(
        self,
        *,
        capability_id: str,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> float | None:
        """
        Return the historical success rate (successes / total, in
        [0, 1]) for the given capability, optionally narrowed to a
        specific provider/model. Returns None when no data exists yet
        for the given filters, so callers can degrade to a neutral
        score rather than treating "no data" as "zero success".
        """
