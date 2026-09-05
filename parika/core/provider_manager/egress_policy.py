from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum

class EgressDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"

@dataclass(frozen=True, slots=True)
class EgressResult:
    decision: EgressDecision
    reason: str = ""

class CloudEgressPolicy:
    """Conservative, explicit cloud egress gate; no content rewriting."""
    def __init__(self, *, allow: bool = False, allow_native_tools: bool = False):
        self.allow = allow
        self.allow_native_tools = allow_native_tools
    def check(self, *, category: str = "context", implementation: str | None = None) -> EgressResult:
        if implementation == "parika_native" and not self.allow_native_tools:
            return EgressResult(EgressDecision.DENY, "PARIKA-native tool egress is denied")
        if not self.allow:
            return EgressResult(EgressDecision.DENY, f"cloud egress denied for {category}")
        return EgressResult(EgressDecision.ALLOW)
