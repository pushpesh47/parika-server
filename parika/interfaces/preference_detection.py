"""
PARIKA Interfaces - Preference Detection

Deterministic, pattern-based detection of user-stated preferences in
chat turns, used by `InterfaceSession.save()` to write durable
`Memory(kind=PREFERENCE, ...)` records.

A small `PreferenceRule` ABC plus a `DEFAULT_PREFERENCE_RULES` tuple.
Kept deterministic and rule-based (not an LLM call) for predictable
cost/latency. Unlike the domain/tool-relevance keyword routing AI
Context Engineering removed (see `Request_Understanding.md`), this
module recognizes a fixed, narrow set of preference-phrasing patterns
for a single purpose (durable Memory record extraction on session
save) that never grows or needs updating when a new Capability is
registered, so it is not part of that removal.

This lives in the Interfaces layer, not Core: Interfaces has no
"does not reason" constraint, but pattern matching is still preferred
here over a hidden LLM call.
"""

from __future__ import annotations

import re

from abc import ABC, abstractmethod


class PreferenceRule(ABC):
    """A single deterministic preference-detection pattern."""

    id: str

    @abstractmethod
    def evaluate(self, text: str) -> str | None:
        """
        Return the detected preference statement (a normalized,
        human-readable string) if `text` matches this rule's pattern,
        or None otherwise.
        """


class _RegexPreferenceRule(PreferenceRule):
    """A preference rule backed by a single compiled regex."""

    def __init__(self, rule_id: str, pattern: str) -> None:
        self.id = rule_id
        self._pattern = re.compile(pattern, re.IGNORECASE)

    def evaluate(self, text: str) -> str | None:
        match = self._pattern.search(text)

        if match is None:
            return None

        return match.group(0).strip()


ExplicitPreferenceRule = _RegexPreferenceRule(
    "explicit_preference", r"\bi (?:prefer|like|love|want)\b[^.!?\n]*"
)
AlwaysInstructionRule = _RegexPreferenceRule(
    "always_instruction", r"\balways\b[^.!?\n]*"
)
NeverInstructionRule = _RegexPreferenceRule(
    "never_instruction", r"\bnever\b[^.!?\n]*"
)
RememberInstructionRule = _RegexPreferenceRule(
    "remember_instruction", r"\bremember (?:that )?\b[^.!?\n]*"
)

DEFAULT_PREFERENCE_RULES: tuple[PreferenceRule, ...] = (
    ExplicitPreferenceRule,
    AlwaysInstructionRule,
    NeverInstructionRule,
    RememberInstructionRule,
)


def detect_preferences(
    text: str,
    rules: "tuple[PreferenceRule, ...] | None" = None,
) -> tuple[str, ...]:
    """
    Evaluate every rule against `text` and return every matched
    preference statement, in rule order. Deduplicates identical
    matches.
    """

    active_rules = rules if rules is not None else DEFAULT_PREFERENCE_RULES

    matches: list[str] = []
    seen: set[str] = set()

    for rule in active_rules:
        result = rule.evaluate(text)

        if result is not None and result.lower() not in seen:
            matches.append(result)
            seen.add(result.lower())

    return tuple(matches)
