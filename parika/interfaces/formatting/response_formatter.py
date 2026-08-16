"""
PARIKA Interfaces - Response Formatting

Turns a `ChatTurnResult` into human-readable Markdown-flavored text.
"""

from __future__ import annotations

from parika.interfaces.session import ChatTurnResult

from .error_formatter import format_error


def format_chat_turn(result: ChatTurnResult) -> str:
    """
    Format the outcome of a chat turn for display.

    On success, any tool calls the model made are listed first (so
    users can see when PARIKA reached outside its own knowledge),
    followed by the model's final answer text.
    """

    if not result.succeeded or result.chat_response is None:
        return format_error(
            result.error_message or "The request did not complete."
        )

    chat_response = result.chat_response

    lines: list[str] = []

    for invocation in chat_response.tool_invocations:
        status = "ok" if invocation.succeeded else "failed"
        lines.append(
            f"[used tool `{invocation.name}` - {status}]"
        )

    lines.append(chat_response.message.content)

    return "\n".join(line for line in lines if line)
