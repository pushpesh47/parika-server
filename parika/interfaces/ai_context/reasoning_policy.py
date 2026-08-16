"""
PARIKA AI Context Engineering - Reasoning Policy

Owns ONLY the general, capability-independent reasoning policy
appended to PARIKA's system prompt: the order in which the model
should prefer already-available sources of information over calling a
Tool, and the general principle that a Tool is called only when it
provides information genuinely not already available. Owns no
identity data (see `identity.py`), no memory-authorization/tool-
specific behavior (see `behavior.py`), and no general constraints (see
`constraints.py`).

This policy must remain, and does remain, completely generic: it
never mentions a specific Capability id or tool name, of any current
or future Capability domain. "Memory" and "Knowledge" below refer to
the Core Memory/Knowledge subsystems
Context Assembly already integrates with generically (see
`memory.py`/`knowledge.py`/`context_builder.py`) - not to any
Capability Registry entry - so naming them here is not
capability-specific knowledge. Every fact about a *specific* Tool
(when to use it, when to avoid it, what it requires, how to read its
results/failures) instead lives entirely in that Tool's own Tool
Affordance Contract, composed into its advertised description by
`tool_context.py` -- this policy only ever states the general
ordering a Tool Affordance Contract is read within, never a
substitute for one.
"""

from __future__ import annotations

REASONING_POLICY = (
    "Before using any tool, reason in this order, and stop at the "
    "first source that already answers the question: "
    "(1) Assistant Identity, already stated above, for any question "
    "about who you are; "
    "(2) this current conversation's own message history, already "
    "visible to you; "
    "(3) any Memory already injected into this context above, if "
    "present; "
    "(4) any Knowledge already injected into this context above, if "
    "present; "
    "(5) the result of an earlier Tool call already made in this same "
    "conversation. "
    "Only call a Tool when none of the above already answers the "
    "question. Never call a Tool simply because it is available, and "
    "never call a Tool to re-fetch information you already have from "
    "an earlier source in this order. "
    "Each Tool's own description below states when it should be "
    "used, when it should be avoided, what information it requires "
    "before it can be called, and how to interpret its results and "
    "failures -- follow that guidance for each Tool exactly. If a Tool "
    "states that it requires information you do not have, ask the "
    "user a follow-up question for it rather than guessing."
)
"""
Fixed general reasoning policy text appended to the system prompt (see
`prompt_builder.build_assistant_system_prompt()`). Deliberately not
sourced from `[assistant]` configuration and deliberately silent about
any specific Capability/Tool -- see the module docstring.
"""


def build_reasoning_policy_text() -> str:
    """
    Return the fixed general reasoning policy text.

    Pure function, no arguments: this text never varies by
    Configuration, by turn, or by which Capabilities happen to be
    enabled.
    """

    return REASONING_POLICY
