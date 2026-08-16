"""
PARIKA Policy Evaluation Request

Defines the immutable request submitted to PolicyEngine for
evaluation.

PolicyEngine does not store policies. The applicable PolicyRule
instances are supplied by the caller on every evaluation, sourced from
wherever policy definitions are owned (e.g. the Policies package or
Configuration).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .policy_context import PolicyContext
from .policy_effect import PolicyEffect
from .policy_rule import PolicyRule


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class PolicyEvaluationRequest:
    """
    Immutable request describing a single policy evaluation.

    A PolicyEvaluationRequest carries the PolicyRule instances
    applicable to this evaluation together with the PolicyContext
    they should be evaluated against.
    """

    rules: tuple[PolicyRule, ...]
    """
    PolicyRule instances applicable to this evaluation, supplied by
    the caller.
    """

    context: PolicyContext
    """
    Implementation-neutral facts available to rule predicates.
    """

    default_effect: PolicyEffect = PolicyEffect.ALLOW
    """
    Effect applied when no supplied rule matches the context.
    """

    def __post_init__(self) -> None:
        """
        Normalize mutable inputs into immutable equivalents.
        """

        object.__setattr__(self, "rules", tuple(self.rules))
        object.__setattr__(
            self,
            "context",
            MappingProxyType(dict(self.context)),
        )
