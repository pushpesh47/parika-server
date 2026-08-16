"""
PARIKA Policy Engine Exceptions

Defines the exception hierarchy used by PolicyEngine.

All PolicyEngine-specific exceptions derive from PolicyEngineError.
"""

from __future__ import annotations


class PolicyEngineError(Exception):
    """
    Base exception for all PolicyEngine errors.
    """


class InvalidPolicyEvaluationRequestError(PolicyEngineError):
    """
    Raised when a PolicyEvaluationRequest is structurally invalid.
    """


class InvalidPolicyRuleError(PolicyEngineError):
    """
    Raised when a supplied PolicyRule is structurally invalid.
    """
