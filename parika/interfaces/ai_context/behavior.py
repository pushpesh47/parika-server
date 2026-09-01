"""
PARIKA AI Context Engineering - Assistant Behavior Instructions

Owns ONLY the fixed, capability-independent operating instructions
appended to PARIKA's default Assistant Identity system prompt --
answering identity questions directly, maintaining feminine
self-reference across languages and writing systems, and never
over-claiming that a Tool action succeeded. Owns no identity data
(see `identity.py`), no source-preference ordering
(see `reasoning_policy.py`), and no general constraints
(see `constraints.py`).

Capability Independence: this module never names a specific Capability
id or tool (e.g. it never says "memory_remember"). Every
capability-specific behavioral rule (e.g. exactly when the Memory
Capabilities should or should not be used, and how to report their
results) instead lives entirely in that Capability's own Tool
Affordance Contract (see `tool_context.py` and, for Memory
specifically, `parika/tools/memory/manifest.py`'s
`MEMORY_TOOL_AFFORDANCES`), composed automatically into that Tool's
advertised description -- never hardcoded here.
"""

from __future__ import annotations

BEHAVIOR_INSTRUCTIONS = (
    "Your identity is fully defined above. Answer identity questions only from it; never use a tool. "
    "When referring to yourself, always maintain feminine grammatical gender in every language and writing system. "
    "This applies equally to native scripts, transliterated text, phonetic spellings, and mixed-language text. "
    "When speaking or writing Hindi, including Hindi written in Latin/Roman script (Hinglish or Roman Hindi), "
    "always use feminine self-referential forms such as 'main karti hoon', 'main jaaungi', 'main bataungi', "
    "and 'main samajhti hoon', never masculine forms such as 'main karta hoon', 'main jaaunga', "
    "'main bataunga', or 'main samajhta hoon'. "
    "Never claim a tool action succeeded unless the corresponding tool call succeeded."
)
"""
Fixed operating instructions appended to the default Assistant
Identity system prompt (see `prompt_builder.build_assistant_system_prompt()`).
Deliberately not sourced from `[assistant]` configuration: these are
behavioral instructions, not identity data, so they stay constant
regardless of how an operator configures PARIKA's name/creator/
purpose/etc.

This text alone is necessarily advisory, not enforced -- a model can
still deviate from it -- so each rule it states generically is backed
by a deterministic layer that holds regardless of model compliance:

- `tool_context.discover_tool_specs()`'s authorization gates (reading
  each Capability's own `identity_sensitive`/`authorization_predicate`
  metadata) never advertise a Capability flagged `identity_sensitive`
  at all for an Assistant Identity question, so a model cannot call it
  for that turn regardless of what this text says (see e.g. the Memory
  Capabilities' own metadata in `parika/modules/memory/driver.py`).
- Each Tool's own driver (e.g. `MemoryToolDriver`) only ever reports
  success after the underlying action genuinely completed; this text
  only discourages a model from *claiming* success without having
  actually called the Tool at all.
"""


def build_behavior_text() -> str:
  """
  Return the fixed behavioral operating instructions text.

  Pure function, no arguments: this text never varies by
  Configuration or by turn.
  """

  return BEHAVIOR_INSTRUCTIONS
