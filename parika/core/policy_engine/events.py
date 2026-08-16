"""
PARIKA Policy Engine Events

Defines the immutable events published by PolicyEngine.

Events notify the EventBus whenever a policy evaluation produces a
decision. Events are immutable data containers and carry no business
logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from .decision import PolicyDecision


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyEvaluatedEvent:
    """Published after PolicyEngine produces a PolicyDecision."""

    decision: PolicyDecision
    """The resolved PolicyDecision."""
