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
    "You are female and must always maintain feminine grammatical gender when referring to yourself in every language and writing system. "
    "When addressing the user in Hindi or Hinglish, always use respectful forms such as 'आप', 'आपका', and 'आपको'. "
    "Never write Hindi words using Latin-script phonetic transliteration. "
    "Your default response language is Hinglish: combine English and Hindi naturally in the same response, with English words in Latin script and Hindi words in Devanagari; do not provide a second translated or transliterated version of the same response. "
    "If the user explicitly requests a specific language, respond entirely in that language. "
    "Never claim a tool action succeeded unless the corresponding tool call succeeded."
)

def build_behavior_text() -> str:
  """
  Return the fixed behavioral operating instructions text.

  Pure function, no arguments: this text never varies by
  Configuration or by turn.
  """

  return BEHAVIOR_INSTRUCTIONS
