"""
PARIKA Policy Decision

Defines the immutable PolicyDecision produced by PolicyEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .policy_effect import PolicyEffect


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class PolicyDecision:
    """
    Immutable result of a policy evaluation.

    A PolicyDecision reports the final resolved PolicyEffect together
    with the rule that determined it, if any.
    """

    effect: PolicyEffect
    """
    Final resolved effect after conflict resolution.
    """

    matched_rule_id: str | None
    """
    Identifier of the PolicyRule that determined this decision.

    None when no rule matched and the default effect was applied.
    """

    reason: str | None = None
    """
    Optional human-readable explanation of the decision.
    """

    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when the decision was produced.
    """

    @property
    def is_allowed(self) -> bool:
        """
        Convenience accessor equivalent to `effect is PolicyEffect.ALLOW`.
        """

        return self.effect is PolicyEffect.ALLOW
