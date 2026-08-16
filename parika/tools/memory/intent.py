"""
PARIKA Memory Tool - Explicit Memory Intent Detection

Deterministic, keyword-based detection of whether a user message is an
*explicit* request to permanently remember/save/store/note something
(PARIKA Memory Subsystem Refactor's "Strictly Explicit Memory"
requirement -- see `manifest.MEMORY_TOOL_AFFORDANCES["memory.remember"]`'s
description).

This module -- and the authorization decision it makes -- is owned by
the Memory Tool itself, never by AI Context Engineering: it is
capability-specific knowledge (meaningful only for `memory.remember`),
so per PARIKA's Capability Independence rule, AI Context Engineering
must never import or embed it directly. Instead, `has_explicit_memory_intent`
is registered as this Capability's own `CapabilityDefinition.
metadata["authorization_predicate"]` (see
`parika/modules/memory/driver.py`), a generic, opaque
`Callable[[str], bool]` hook AI Context Engineering invokes without
knowing what it checks or which capability it belongs to (see
`parika/interfaces/ai_context/tool_context.py`).

This is the enforcement half of the "Strictly Explicit Memory"
requirement. The tool-spec description and the system prompt's
behavioral instructions (see `ai_context/behavior.py`) already *tell*
the model to only call `memory_remember` for an explicit request --
but that is necessarily advisory: a model can still deviate from it.
`has_explicit_memory_intent()` is instead consulted through the
generic authorization-predicate hook to decide whether
`memory_remember` is even *included* in the tool roster advertised to
the model for this turn at all. When this function returns False,
`memory_remember` is never advertised, so the model has no way to call
it for that turn regardless of the provider or model in use -- an
unadvertised tool name that a model still hallucinates a call for is
rejected as "unknown tool" before Brain/Planner/MemoryManager is ever
reached (see `ToolCallResolver.resolve()`).

This makes explicit-memory authorization deterministic and
provider-agnostic by construction, exactly like Assistant Identity
Protection (`identity_guard.py`) is deterministic and provider-agnostic
by living in `MemoryToolDriver`, the single choke point every
`memory.remember` call passes through.

Deliberately conservative: only recognizes the trigger verb/phrase at
the *start* of the message (allowing a small set of leading filler
words such as "please"/"hey"/"okay"), never mid-sentence. This
intentionally does not recognize phrasing such as "so, please
remember my name is Pushpesh" (the verb is not near the start) or "do
you remember what I told you?" (an ordinary question, not a request) -
favoring precision over recall, the same trade-off `identity_guard.py`
documents for Assistant Identity Protection: guaranteeing that ordinary
conversation never silently creates a permanent memory takes priority
over recognizing every possible phrasing of an explicit request.
"""

from __future__ import annotations

import re

_EXPLICIT_MEMORY_INTENT_PATTERN = re.compile(
    r"^\s*(?:(?:please|hey|ok(?:ay)?)[\s,]+)*"
    r"(?:"
    r"(?:remember|save|store|note|memorize|memorise)\b"
    r"|don'?t\s+forget\b"
    r"|add\s+(?:this|that|it)\s+to\s+memory\b"
    r"|keep\s+(?:this|that|it)\s+in\s+mind\b"
    r"|make\s+a\s+note\b"
    r"|jot\s+(?:this|that|it)\s+down\b"
    r")",
    re.IGNORECASE,
)
"""
Matches an explicit-memory instruction verb/phrase anchored at the
start of the message (after optional leading filler words). See the
module docstring for why this is intentionally start-anchored rather
than a bare `\\bremember\\b` search anywhere in the text.
"""


def has_explicit_memory_intent(text: str) -> bool:
    """
    Return True if `text` is an explicit request to permanently
    remember/save/store/note something (e.g. "Remember that...",
    "Remember my name is Pushpesh.", "Save this.", "Store this.",
    "Don't forget this.", "Add this to memory.").

    Returns False for ordinary statements, questions, or conversation
    that merely *contains* information the user did not ask to have
    stored (e.g. "My name is Pushpesh.", "I like Python.", "My
    daughter is Kavya.") -- these must never be treated as memory
    requests, per the PARIKA Memory Subsystem Refactor's "Strictly
    Explicit Memory" requirement.
    """

    return bool(_EXPLICIT_MEMORY_INTENT_PATTERN.search(text))
