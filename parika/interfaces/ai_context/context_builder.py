"""
PARIKA AI Context Engineering - Context Builder

Owns ONLY assembling the final Memory/Knowledge AI context for one
chat turn: calls `Brain.assemble_context()` (Context Assembly) and
renders its result via `memory.py`/`knowledge.py` into zero or one
system-role, provider-independent `ChatMessage`. Never retrieves
Session context (see `session_context.py`) and never builds Goals,
prompts, or tool information itself.
"""

from __future__ import annotations

from uuid import uuid4

from parika.core.brain.context_engine import ContextBundle
from parika.core.brain.exceptions import ContextEngineUnavailableError
from parika.core.planner.goal import Goal
from parika.core.provider_manager.chat_message import ChatMessage
from parika.modules.chat.driver import CHAT_CAPABILITY_ID

from . import knowledge, memory
from ..runtime import ParikaRuntime


def assemble_context_messages(
    runtime: ParikaRuntime,
    *,
    text: str,
    session_id: str | None,
    conversation_message_count: int,
) -> tuple[tuple[ChatMessage, ...], ContextBundle | None]:
    """
    Automatically retrieve relevant Memory/Knowledge/Experience
    context for `text` via `Brain.assemble_context()` (Context
    Assembly, see `context_engine/retrieval_ordering.py`), and render
    it as zero or one additional system-role, provider-independent
    `ChatMessage` via `memory.render_memory_section()`/
    `knowledge.render_knowledge_section()`.

    This is what makes Context Assembly automatic and mandatory for
    every chat turn: `submit_text()` calls this before Planner ever
    runs, without the model ever needing to ask for memories
    explicitly. Only Memory/Knowledge results become injected content
    -- Experience never contributes retrieved text (it influences
    Planner's own scoring separately, via `ExperienceRule`).

    Never raises: a Context Assembly failure (e.g. no `memory_manager`
    configured) degrades to "no additional context" rather than
    breaking the chat turn.

    Returns
    -------
    tuple[tuple[ChatMessage, ...], ContextBundle | None]
        The messages to insert (possibly empty), and the raw
        `ContextBundle` (or `None` if Context Assembly was
        unavailable) -- callers such as `InterfaceSession` use the
        bundle purely for `/status` diagnostics.
    """

    preliminary_goal = Goal(
        id=uuid4().hex,
        capability_id=CHAT_CAPABILITY_ID,
        inputs={"message": text} if text else {},
        metadata={"session_id": session_id} if session_id else {},
    )

    try:
        bundle = runtime.brain.assemble_context(
            preliminary_goal,
            conversation_message_count=conversation_message_count,
        )
    except ContextEngineUnavailableError:
        return (), None

    sections = [
        section
        for section in (
            memory.render_memory_section(bundle),
            knowledge.render_knowledge_section(bundle),
        )
        if section is not None
    ]

    if not sections:
        return (), bundle

    return (ChatMessage(role="system", content="\n\n".join(sections)),), bundle
