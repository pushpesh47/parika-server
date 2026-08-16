"""
PARIKA AI Context Engineering - Conversation Assembly

Owns ONLY assembling the effective conversation message list for one
turn: splicing freshly retrieved context (Memory/Knowledge via
`context_builder.py`, Session excerpts via `session_context.py`) into
the right position relative to the rolling conversation history,
without ever mutating that history itself. Never retrieves or renders
any context; that remains `context_builder.py`/`session_context.py`'s
job.
"""

from __future__ import annotations

from parika.core.provider_manager.chat_message import ChatMessage


def assemble_conversation_messages(
    history: tuple[ChatMessage, ...],
    injected_messages: tuple[ChatMessage, ...],
) -> tuple[ChatMessage, ...]:
    """
    Splice `injected_messages` immediately before the newest message
    in `history`, or return `history` unchanged when there is nothing
    to inject.

    `history` is the session's rolling conversation (system prompt +
    every prior user/assistant message + this turn's newest,
    just-appended user message). `injected_messages` is typically the
    concatenation of `context_builder.assemble_context_messages()`'s
    and `session_context.assemble_session_retrieval_messages()`'s
    results -- zero or more additional system-role messages. Context
    is re-assembled fresh every turn and injected only into the
    returned tuple, never persisted into `history` itself.

    Args:
        history:
            The full rolling conversation, oldest first, ending with
            the newest user message.

        injected_messages:
            Zero or more additional messages (typically system-role
            Memory/Knowledge/Session content) to insert immediately
            before that newest message.

    Returns:
        The effective message list to send to the model for this
        turn.
    """

    if not injected_messages:
        return tuple(history)

    return (*history[:-1], *injected_messages, history[-1])
