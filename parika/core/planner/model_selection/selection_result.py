"""
PARIKA Planner - Model Selection Result

Defines `ModelSelectionResult`: the complete, immutable record of one
provider/model selection decision.

Rather than the selector returning only the winning `ProviderModel`,
it returns this richer object so that logging, diagnostics, and any
future telemetry/metrics/dashboard consumer can be built against it
without ever needing to change its shape or re-run selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from parika.core.provider_manager.provider_model import ProviderModel

from .evaluation import CandidateEvaluation
from .requirements import ExecutionRequirements, ThinkingMode
from .rules import RuleOutcome


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelSelectionResult:
    """
    Immutable, complete record of a single provider/model selection
    decision.
    """

    requirements: ExecutionRequirements
    """The requirements this decision was evaluated against."""

    selected_provider_id: str | None = None
    selected_model: ProviderModel | None = None

    thinking_mode: ThinkingMode = ThinkingMode.AUTO
    """Configured reasoning mode for this decision's ReasoningLevel."""

    reasoning_enabled: bool | None = None
    """
    The resolved `RequestOptions.reasoning` value: `True`/`False` for
    an explicit ON/OFF `thinking_mode`, or `None` for AUTO (no
    explicit override; the provider's own default applies).
    """

    total_score: float | None = None
    breakdown: tuple[RuleOutcome, ...] = field(default_factory=tuple)
    reason: str = ""

    evaluated_candidates: tuple[CandidateEvaluation, ...] = field(
        default_factory=tuple
    )
    """
    Every candidate considered, accepted or rejected, in a
    deterministic order - the full transparency trail for this
    decision.
    """

    selection_duration_seconds: float = 0.0
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def succeeded(self) -> bool:
        """
        Whether a Provider model was actually selected.
        """

        return self.selected_model is not None
