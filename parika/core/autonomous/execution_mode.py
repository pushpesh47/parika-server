"""
PARIKA Autonomous Execution - Execution Mode

Defines the execution mode and admission decision types for autonomous execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional


class ExecutionMode(StrEnum):
    """Execution strategy for a user objective."""
    NORMAL = "normal"
    AUTONOMOUS = "autonomous"


class AdmissionState(StrEnum):
    """Result of autonomous admission evaluation."""
    ADMITTED = "admitted"
    DENIED_POLICY = "denied_policy"
    DENIED_PERMISSIONS = "denied_permissions"
    DENIED_RESOURCES = "denied_resources"
    UNAVAILABLE_RUNTIME = "unavailable_runtime"
    CONFIG_DISABLED = "config_disabled"
    INVALID_PROPOSAL = "invalid_proposal"
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True, slots=True, kw_only=True)
class AdmissionDecision:
    """Deterministic admission decision for autonomous execution."""
    proposed_semantic_mode: ExecutionMode
    admitted_mode: ExecutionMode
    admission_state: AdmissionState
    reason: str
    policy_decision_id: Optional[str] = None
    permission_details: dict[str, Any] = field(default_factory=dict)
    resource_details: dict[str, Any] = field(default_factory=dict)