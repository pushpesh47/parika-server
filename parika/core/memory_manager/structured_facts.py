"""
PARIKA Memory - Structured Fact Extraction & Grouping

Deterministic, stdlib-only recognition of a small, curated set of
"slot" statements (e.g. "my name is X", "my nickname is X", "I use the
X framework") that belong to a well-known, semantically related group
(Profile, Programming Preferences, Travel Preferences).

Used by `remember.py`'s `remember()` to satisfy the PARIKA Memory
Subsystem Refactor's "Semantic Merge" requirement: when a new slot
statement is recognized, it is merged into the single canonical memory
already tracking that group (creating one if none exists yet) instead
of becoming its own, disconnected memory row -- e.g. "Remember my name
is Pushpesh." followed later by "Remember my nickname is Push."
produces one merged Profile memory, never two.

Deliberately narrow and rule-based (never an LLM call), matching the
same stdlib-only, deterministic philosophy already used by
`categorization.py` and `preference_detection.py`. Content that does
not match any pattern here is left completely untouched and falls
back to `remember()`'s ordinary near-duplicate handling.

Isolation (PARIKA Memory Subsystem Refactor requirement): only members
of the *same* recognized group are ever combined -- e.g. a favourite
food statement is never grouped with a favourite IDE statement, since
neither matches any rule here at all. Two different groups (e.g.
Profile and Travel Preferences) are also never merged with each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .memory_category import MemoryCategory


@dataclass(frozen=True, slots=True)
class SlotMatch:
    """One recognized (group, slot, value) structured fact."""

    group_key: str
    """Stable identifier of the structured memory this slot belongs
    to (e.g. "profile"). Stored in `Memory.metadata["structured_group"]`
    so later `remember()` calls can find the same canonical memory to
    merge into."""

    group_title: str
    """Human-readable heading rendered at the top of the group's
    content (e.g. "Profile")."""

    slot_name: str
    """Human-readable label for this specific fact within the group
    (e.g. "Nickname")."""

    value: str
    """The extracted value (e.g. "Push")."""

    category: MemoryCategory
    """The MemoryCategory this group's memory is always stored under,
    regardless of what category (if any) the caller supplied."""


_LANGUAGE_KEYWORDS: frozenset[str] = frozenset(
    {
        "python", "javascript", "typescript", "java", "c++", "c#", "go",
        "golang", "rust", "ruby", "php", "swift", "kotlin", "c",
        "scala", "haskell", "perl", "r", "dart", "elixir", "clojure",
    }
)

_FRAMEWORK_KEYWORDS: frozenset[str] = frozenset(
    {
        "laravel", "django", "flask", "react", "vue", "angular",
        "next.js", "nextjs", "express", "spring", "rails", ".net",
        "dotnet", "fastapi", "svelte", "symfony", "nestjs",
    }
)

_TRANSPORT_KEYWORDS: frozenset[str] = frozenset(
    {"train", "flight", "plane", "airplane", "car", "bus", "ship", "bike", "motorcycle"}
)


def _clean(value: str) -> str:
    """Strip surrounding whitespace and trailing sentence punctuation."""

    return value.strip().strip(".!?").strip()


_NICKNAME_PATTERN = re.compile(
    r"\bmy nick\s?name is\s+([^.!?\n]+)", re.IGNORECASE
)
_NAME_PATTERN = re.compile(
    r"\bmy name is\s+([^.!?\n]+)", re.IGNORECASE
)
_SEAT_PATTERN = re.compile(
    r"\bi (?:prefer|like)\s+([A-Za-z]+)\s+seats?\b", re.IGNORECASE
)
_PREFERRED_TRANSPORT_PATTERN = re.compile(
    r"\bmy preferred transport is\s+([A-Za-z]+)", re.IGNORECASE
)
_GENERIC_TRANSPORT_PATTERN = re.compile(
    r"\bi (?:prefer|like)\s+(?:to travel by\s+)?([A-Za-z]+)\b",
    re.IGNORECASE,
)
_LANGUAGE_STATEMENT_PATTERN = re.compile(
    r"\bmy (?:preferred|favou?rite) language is\s+([A-Za-z0-9+#. ]+)",
    re.IGNORECASE,
)
_FRAMEWORK_STATEMENT_PATTERN = re.compile(
    r"\bmy (?:preferred|favou?rite) framework is\s+([A-Za-z0-9+#. ]+)",
    re.IGNORECASE,
)
_USE_FRAMEWORK_PATTERN = re.compile(
    r"\bi use\s+(?:the\s+)?([A-Za-z0-9+#.]+)(?:\s+framework)?\b",
    re.IGNORECASE,
)
_GENERIC_TECH_PATTERN = re.compile(
    r"\bi (?:use|like|prefer|code in|program in)\s+(?:the\s+)?"
    r"([A-Za-z0-9+#.]+)\b",
    re.IGNORECASE,
)


def extract_slot(content: str) -> SlotMatch | None:
    """
    Return the recognized (group, slot, value) for `content`, or None
    if it matches none of this module's curated patterns.
    """

    match = _NICKNAME_PATTERN.search(content)

    if match:
        return SlotMatch(
            group_key="profile",
            group_title="Profile",
            slot_name="Nickname",
            value=_clean(match.group(1)),
            category=MemoryCategory.PROFILE,
        )

    match = _NAME_PATTERN.search(content)

    if match:
        return SlotMatch(
            group_key="profile",
            group_title="Profile",
            slot_name="Name",
            value=_clean(match.group(1)),
            category=MemoryCategory.PROFILE,
        )

    match = _SEAT_PATTERN.search(content)

    if match:
        return SlotMatch(
            group_key="travel_preferences",
            group_title="Travel Preferences",
            slot_name="Preferred seat",
            value=_clean(match.group(1)).capitalize(),
            category=MemoryCategory.PREFERENCE,
        )

    match = _PREFERRED_TRANSPORT_PATTERN.search(content)

    if match:
        return SlotMatch(
            group_key="travel_preferences",
            group_title="Travel Preferences",
            slot_name="Preferred transport",
            value=_clean(match.group(1)).capitalize(),
            category=MemoryCategory.PREFERENCE,
        )

    match = _GENERIC_TRANSPORT_PATTERN.search(content)

    if match:
        candidate = _clean(match.group(1)).lower()

        if candidate not in _TRANSPORT_KEYWORDS and candidate.endswith("s"):
            singular = candidate[:-1]

            if singular in _TRANSPORT_KEYWORDS:
                candidate = singular

        if candidate in _TRANSPORT_KEYWORDS:
            return SlotMatch(
                group_key="travel_preferences",
                group_title="Travel Preferences",
                slot_name="Preferred transport",
                value=candidate.capitalize(),
                category=MemoryCategory.PREFERENCE,
            )

    match = _LANGUAGE_STATEMENT_PATTERN.search(content)

    if match:
        return SlotMatch(
            group_key="programming_preferences",
            group_title="Programming Preferences",
            slot_name="Language",
            value=_clean(match.group(1)),
            category=MemoryCategory.PREFERENCE,
        )

    match = _FRAMEWORK_STATEMENT_PATTERN.search(content)

    if match:
        return SlotMatch(
            group_key="programming_preferences",
            group_title="Programming Preferences",
            slot_name="Framework",
            value=_clean(match.group(1)),
            category=MemoryCategory.PREFERENCE,
        )

    match = _USE_FRAMEWORK_PATTERN.search(content)

    if match:
        candidate = _clean(match.group(1))

        if candidate.lower() in _FRAMEWORK_KEYWORDS:
            return SlotMatch(
                group_key="programming_preferences",
                group_title="Programming Preferences",
                slot_name="Framework",
                value=candidate,
                category=MemoryCategory.PREFERENCE,
            )

        if candidate.lower() in _LANGUAGE_KEYWORDS:
            return SlotMatch(
                group_key="programming_preferences",
                group_title="Programming Preferences",
                slot_name="Language",
                value=candidate,
                category=MemoryCategory.PREFERENCE,
            )

    match = _GENERIC_TECH_PATTERN.search(content)

    if match:
        candidate = _clean(match.group(1))
        lowered = candidate.lower()

        if lowered in _LANGUAGE_KEYWORDS:
            return SlotMatch(
                group_key="programming_preferences",
                group_title="Programming Preferences",
                slot_name="Language",
                value=candidate,
                category=MemoryCategory.PREFERENCE,
            )

        if lowered in _FRAMEWORK_KEYWORDS:
            return SlotMatch(
                group_key="programming_preferences",
                group_title="Programming Preferences",
                slot_name="Framework",
                value=candidate,
                category=MemoryCategory.PREFERENCE,
            )

    return None


def render_structured_content(title: str, slots: dict[str, str]) -> str:
    """
    Deterministically render a group's slots into the canonical
    Memory `content` text:

        {title}

        {slot_1}:
        {value_1}

        {slot_2}:
        {value_2}

    Slot order follows `slots`' own (insertion) order, so the first
    remembered slot always renders first and later-merged slots are
    appended after it.
    """

    body = "\n\n".join(f"{name}:\n{value}" for name, value in slots.items())

    return f"{title}\n\n{body}"
