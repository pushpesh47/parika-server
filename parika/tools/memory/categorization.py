"""
PARIKA Memory Tool - Automatic Categorization

Deterministic, pattern-based fallback categorization used by
`memory.remember` when the caller (the model) does not explicitly
supply a `category` argument -- "Automatic categorization is
preferred. Allow manual override." (Phase 1 Completion Specification
section 5).

Structured like `preference_detection.py`: a small, ordered set of
regex rules, first match wins, falling back to `MemoryCategory.FACT`.
Never an LLM call -- this stays deterministic and inexpensive, and an
explicit `category` argument from the caller always takes precedence
over this heuristic entirely (see `driver.py`). This classifies the
*content* of a memory already explicitly authorized for storage; it
is unrelated to, and unaffected by, the capability/tool-relevance
routing removal described in `Request_Understanding.md`.
"""

from __future__ import annotations

import re

from parika.core.memory_manager.memory_category import MemoryCategory

_RULES: tuple[tuple[re.Pattern[str], MemoryCategory], ...] = (
    (re.compile(r"\b(my name is|call me|i am called)\b", re.IGNORECASE), MemoryCategory.PROFILE),
    (re.compile(r"\b(prefer|like|love|hate|dislike|favorite)\b", re.IGNORECASE), MemoryCategory.PREFERENCE),
    (re.compile(r"\b(my (wife|husband|partner|friend|colleague|manager|boss|son|daughter|mother|father|sister|brother))\b", re.IGNORECASE), MemoryCategory.RELATIONSHIP),
    (re.compile(r"\b(goal|want to|plan to|aim to|hope to)\b", re.IGNORECASE), MemoryCategory.GOAL),
    (re.compile(r"\b(project|working on|building|repository)\b", re.IGNORECASE), MemoryCategory.PROJECT),
    (re.compile(r"\b(skilled at|good at|know how to|experienced (in|with))\b", re.IGNORECASE), MemoryCategory.SKILL),
    (re.compile(r"\b(remind me|reminder|don't forget)\b", re.IGNORECASE), MemoryCategory.REMINDER_REFERENCE),
)


def categorize(content: str) -> MemoryCategory:
    """
    Return the first matching category for `content`, or
    `MemoryCategory.FACT` if nothing matches.
    """

    for pattern, category in _RULES:
        if pattern.search(content):
            return category

    return MemoryCategory.FACT
