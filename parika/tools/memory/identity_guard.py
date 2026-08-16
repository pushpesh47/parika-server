"""
PARIKA Memory Tool - Assistant Identity Protection

Deterministic guard preventing `memory.remember` from ever persisting
Assistant Identity information (see `chat_capability.
build_assistant_system_prompt()`) as if it were a user memory.
Assistant Identity is owned exclusively by Configuration/Runtime
(PARIKA Memory Subsystem Refactor, Requirement A) -- it must never be
written into MemoryManager, regardless of which model/provider decided
to call `memory_remember` or why. This check runs unconditionally
inside `MemoryToolDriver` (see `driver.py`), the single choke point
every `memory.remember` call passes through for every provider, so it
is provider-agnostic by construction.

Two independent, stdlib-only checks combine (either one alone is
sufficient to flag content as identity-related):

1. `content` contains one of the assistant's own configured identity
   values (name/full_name/nick_name) as a substring -- grounded
   directly in Configuration, the single source of truth for
   identity, so it automatically follows however an operator
   configures PARIKA's name/nickname/full name.

2. `content` matches a small set of self-referential phrasings (e.g.
   "your creator", "created you", "I am an AI/assistant") that
   describe the assistant rather than the user, independent of
   whatever name the assistant happens to be configured with.

This is deliberately conservative: a legitimate user memory that
happens to mention the assistant's configured name (e.g. "remember my
dog is named Max" when the assistant happens to also be named "Max")
would also be rejected. That trade-off is intentional -- guaranteeing
Requirement A takes priority over maximizing recall for a narrow,
low-probability edge case. See the Final Report's "Remaining technical
debt" section.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parika.core.configuration.configuration import Configuration

_IDENTITY_CONFIG_KEYS: tuple[str, ...] = (
    "assistant.name",
    "assistant.full_name",
    "assistant.nick_name",
)
"""
Configuration keys whose values are treated as the assistant's own
identifying names. Deliberately excludes `assistant.creator`/
`assistant.organization`/etc.: those are *attributes about* the
assistant, not names *of* the assistant, and would be far too likely
to collide with legitimate user content (e.g. a creator name that is
also a common human name) if matched as a bare substring - they are
still protected, but only through the self-referential patterns below.
"""

_SELF_REFERENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\byour (?:name|nick\s?name|full name|creator|organization|"
        r"purpose|description|version)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:created|made|built)\s+(?:me|you)\b", re.IGNORECASE),
    re.compile(
        r"\byou (?:were|are)\s+(?:created|made|built|called|named)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy (?:creator|purpose|version|organization)\s+is\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bi(?:'m| am)\s+(?:an?\s+)?(?:ai|assistant)\b", re.IGNORECASE),
    re.compile(r"\bi was created by\b", re.IGNORECASE),
)
"""
Self-referential identity phrasings recognized independent of the
assistant's configured name -- e.g. an assistant-composed sentence
like "I was created by Pushpesh Sharma" or "PARIKA is a local-first
...". These describe the assistant, not the user, regardless of
Configuration.
"""

_IDENTITY_QUESTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwho\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:should|do)\s+i\s+call\s+you\b", re.IGNORECASE),
)
"""
Direct identity *questions* recognized in addition to
`_SELF_REFERENTIAL_PATTERNS` -- e.g. "Who are you?", "What are you?",
"What should I call you?". Separate from `_SELF_REFERENTIAL_PATTERNS`
because those describe *content a model might compose about itself*
(the shape a `memory.remember` argument would take), while these
describe a *question a user asks the assistant* (the shape a chat
message takes) -- `is_identity_query()` below combines both since a
message could take either form.
"""


def build_identity_terms(configuration: "Configuration | None") -> frozenset[str]:
    """
    Extract the assistant's own configured identity names (name, full
    name, nickname) from Configuration, lowercased, for use by
    `is_assistant_identity_content()`.

    Parameters
    ----------
    configuration:
        The loaded Configuration to read `[assistant]` values from, or
        None (e.g. in a test double with no Configuration available) -
        identity protection then relies solely on the self-referential
        patterns, still active unconditionally.

    Returns
    -------
    frozenset[str]
        Lowercased, non-empty identity name values.
    """

    if configuration is None:
        return frozenset()

    terms: set[str] = set()

    for key in _IDENTITY_CONFIG_KEYS:
        value = configuration.get(key, "")

        if isinstance(value, str) and value.strip():
            terms.add(value.strip().lower())

    return frozenset(terms)


def is_assistant_identity_content(
    content: str, identity_terms: frozenset[str]
) -> bool:
    """
    Return True if `content` describes Assistant Identity (the
    assistant's own name/creator/purpose/version/etc.) rather than a
    fact about the user, per this module's docstring.

    Parameters
    ----------
    content:
        The candidate `memory.remember` content to check.

    identity_terms:
        The assistant's configured identity names, from
        `build_identity_terms()`.

    Returns
    -------
    bool
        True if `content` should never be persisted as a memory.
    """

    lowered = content.lower()

    for term in identity_terms:
        if term and re.search(rf"\b{re.escape(term)}\b", lowered):
            return True

    return any(pattern.search(content) for pattern in _SELF_REFERENTIAL_PATTERNS)


def is_identity_query(text: str, identity_terms: frozenset[str]) -> bool:
    """
    Return True if `text` is a question directed at the assistant's
    own identity -- e.g. "Who are you?", "What is your name?", "What
    is your nickname?", "Who created you?", "What is your purpose?".

    Used by `parika.interfaces.ai_context.tool_context.
    discover_tool_specs()` to deterministically keep every memory tool
    (`memory_remember`, `memory_search`, `memory_forget`) out of the
    roster advertised to the model for such a turn -- each memory
    Capability flags itself `identity_sensitive` in its own metadata
    (see `parika.tools.memory.manifest.
    MEMORY_IDENTITY_SENSITIVE_CAPABILITIES`), so `tool_context.py`
    consults this generic classifier without knowing it is excluding a
    "memory" capability at all. Identity questions must always be
    answered directly from Configuration/the system prompt (see
    `parika.interfaces.ai_context.identity.build_identity_text()`),
    never by searching or writing to Memory, regardless of model
    behavior (PARIKA Memory & Session Retrieval Finalization, Bug #2).

    Reuses the same self-referential detection as
    `is_assistant_identity_content()` (content a model might compose
    about itself) plus `_IDENTITY_QUESTION_PATTERNS` (a question a
    user asks the assistant) -- either is sufficient.
    """

    lowered = text.lower()

    for term in identity_terms:
        if term and re.search(rf"\b{re.escape(term)}\b", lowered):
            return True

    if any(pattern.search(text) for pattern in _SELF_REFERENTIAL_PATTERNS):
        return True

    return any(pattern.search(text) for pattern in _IDENTITY_QUESTION_PATTERNS)
