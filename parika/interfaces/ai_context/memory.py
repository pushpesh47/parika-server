"""
PARIKA AI Context Engineering - Memory Context

Owns ONLY rendering an already-retrieved permanent Memory result set
(a Brain `ContextBundle`'s `.memories`) into system-prompt-ready text.
Never retrieves Memory itself -- that remains `Brain.
assemble_context()`'s job, orchestrated by `context_builder.py` -- and
never decides whether a Memory result is relevant (Context Assembly/
MemoryManager's job).
"""

from __future__ import annotations

from parika.core.brain.context_engine import ContextBundle


def render_memory_section(bundle: ContextBundle) -> str | None:
    """
    Render `bundle.memories` as a labeled text section.

    Args:
        bundle:
            The `ContextBundle` returned by `Brain.assemble_context()`.

    Returns:
        The rendered section, or `None` if `bundle` has no memories.
    """

    if not bundle.memories:
        return None

    memory_lines = "\n".join(
        f"- {scored.memory.content}" for scored in bundle.memories
    )

    return (
        "Relevant permanent memories about the user (already "
        f"verified, safe to state as fact):\n{memory_lines}"
    )
