"""
PARIKA AI Context Engineering - General Constraints

Reserved, single-responsibility extension point for general,
capability-independent constraint text the AI should understand about
its own operating envelope (e.g. a future note that "some operations
may require your explicit permission before they can run"), distinct
from Assistant Identity (`identity.py`) and behavioral instructions
(`behavior.py`).

This module must never grant, deny, bypass, or enforce any permission,
scope, or policy itself -- Security (Permission System, Policy Engine,
Workspace/Filesystem/Shell Scope, Authentication, Authorization)
remains exactly where it already lives, entirely untouched by AI
Context Engineering. This module may only ever *describe*, in prose,
a constraint some other Core component already enforces
deterministically.

Currently contributes no text to the system prompt: no such general
constraint sentence exists yet, and adding one is out of this
refactor's scope (a structural refactoring only -- see the module
docstring for `parika/interfaces/chat_capability.py`). Kept as its own
module, rather than folded into `behavior.py`, so a future general
constraint has an obvious, single-responsibility home without growing
`behavior.py` into a second, unrelated responsibility.
"""

from __future__ import annotations


def build_constraints_text() -> str:
    """
    Return general constraint text for the system prompt.

    Returns an empty string today (see module docstring) -- observable
    behavior is identical to before this module existed;
    `prompt_builder.py` simply omits an empty section rather than
    inserting a blank sentence.
    """

    return ""
