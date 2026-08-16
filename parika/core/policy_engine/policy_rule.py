"""
PARIKA Policy Rule

Defines the immutable PolicyRule evaluated by PolicyEngine.

A PolicyRule pairs a matching predicate with the effect that applies
when the predicate matches a given PolicyContext. The predicate is
treated as opaque business logic supplied by the component that
defines the rule; PolicyEngine never interprets its internals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .policy_context import PolicyContext
from .policy_effect import PolicyEffect


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class PolicyRule:
    """
    Immutable rule evaluated by PolicyEngine.

    A PolicyRule matches a PolicyContext through an opaque predicate
    callable and carries the PolicyEffect that applies when it
    matches. PolicyEngine treats the predicate as opaque business
    logic and does not interpret its internals.
    """

    id: str
    """
    Unique identifier of the rule.
    """

    effect: PolicyEffect
    """
    Effect applied when the predicate matches.
    """

    predicate: Callable[[PolicyContext], bool]
    """
    Callable that determines whether this rule applies to a given
    PolicyContext.
    """

    priority: int = 0
    """
    Relative priority used for conflict resolution when multiple
    rules match. Higher values take precedence.
    """

    reason: str | None = None
    """
    Optional human-readable explanation of the rule's intent.
    """
