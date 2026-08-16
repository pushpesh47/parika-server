"""
PARIKA Policy Effect

Defines the possible effects a PolicyRule or PolicyDecision may carry.
"""

from __future__ import annotations

from enum import StrEnum


class PolicyEffect(StrEnum):
    """
    Effect associated with a policy rule or a resolved policy
    decision.
    """

    ALLOW = "allow"
    """The evaluated operation is permitted."""

    DENY = "deny"
    """The evaluated operation is forbidden."""
