"""
PARIKA AI Context Engineering - Knowledge Context

Owns ONLY rendering an already-retrieved indexed Knowledge result set
(a Brain `ContextBundle`'s `.knowledge`) into system-prompt-ready
text. Never retrieves Knowledge itself -- that remains `Brain.
assemble_context()`'s job, orchestrated by `context_builder.py`.
"""

from __future__ import annotations

from parika.core.brain.context_engine import ContextBundle


def render_knowledge_section(bundle: ContextBundle) -> str | None:
    """
    Render `bundle.knowledge` as a labeled text section.

    Args:
        bundle:
            The `ContextBundle` returned by `Brain.assemble_context()`.

    Returns:
        The rendered section, or `None` if `bundle` has no knowledge
        results.
    """

    if not bundle.knowledge:
        return None

    knowledge_lines = "\n".join(
        f"- {result.knowledge.title}: {result.knowledge.content}"
        for result in bundle.knowledge
    )

    return f"Relevant indexed knowledge:\n{knowledge_lines}"
