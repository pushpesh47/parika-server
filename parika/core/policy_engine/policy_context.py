"""
PARIKA Policy Context

Defines the type alias for the opaque, implementation-neutral context
supplied to PolicyEngine for evaluation.

PolicyEngine never interprets the contents of a PolicyContext. Only
the predicate supplied by each PolicyRule interprets context values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PolicyContext = Mapping[str, Any]
"""
Implementation-neutral facts available to PolicyRule predicates when
evaluating a policy decision.
"""
