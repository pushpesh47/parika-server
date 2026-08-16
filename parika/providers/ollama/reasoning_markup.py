"""
PARIKA Ollama Provider - Reasoning Markup Suppression

Some model templates - most notably DeepSeek-R1-style and Qwen3
"thinking" templates - wrap a model's internal reasoning narration
("I need to search for that...", "Let me check...") in a structural
`<think>...</think>` (or `<reasoning>...</reasoning>`) block, exactly
the same *kind* of leaked chat-template markup `text_tool_calls.py`
already recovers tool calls from - just denoting reasoning instead of
a tool call. Ollama's `think` request option is meant to route this
content to a separate `message.thinking` response field instead (see
`driver.py`, which never forwards that field to a caller), but not
every model/template honors this consistently, and some emit the
`<think>...</think>` block directly inside `message.content` anyway.

This module recognizes that one structural marker shape - never a
hardcoded natural-language phrase like "I need to search" or "let me
check" - so it generalizes to any model/topic without maintaining an
ever-growing phrase list, exactly mirroring `text_tool_calls.py`'s own
"markup shape, not specific wording" design.

`REASONING_MARKUP_HINTS` is deliberately a separate constant from
`text_tool_calls.MARKUP_HINTS`: a `<think>` block has nothing to do
with tool-call recovery, and must never be handed to
`parse_text_tool_calls()` (which would simply fail to parse it as a
tool call and could not do anything useful with it), nor cause
`looks_like_text_tool_call()` to misfire when only reasoning markup -
never leaked tool-call markup - is present.
"""

from __future__ import annotations

import re

REASONING_MARKUP_HINTS = ("<think>", "<reasoning>")
"""
Opening structural markers denoting a model's own leaked reasoning
narration. Fed to `ReasoningMarkupStreamFilter` below (always, live
streaming or not, tools offered or not - unlike leaked tool-call
markup, this has nothing to do with tool calling) and to
`strip_reasoning_markup()` for the final accumulated content.
"""

_CLOSING_TAGS = {
    "<think>": "</think>",
    "<reasoning>": "</reasoning>",
}

_REASONING_BLOCK_RE = re.compile(
    r"<think>.*?(?:</think>|$)|<reasoning>.*?(?:</reasoning>|$)",
    re.DOTALL | re.IGNORECASE,
)


def strip_reasoning_markup(content: str) -> str:
    """
    Remove any `<think>...</think>` / `<reasoning>...</reasoning>`
    block from `content`, leaving the surrounding genuine answer text
    intact.

    Safe to call unconditionally on every final assistant message,
    streamed or not, tool-calling turn or not: content with no such
    block is returned unchanged (aside from surrounding whitespace
    left by a removed block being trimmed).

    Args:
        content:
            Raw, fully accumulated assistant message content.

    Returns:
        `content` with every reasoning block removed and leading/
        trailing whitespace trimmed.
    """

    if not content:
        return content

    if "<think>" not in content.lower() and "<reasoning>" not in content.lower():
        return content

    return _REASONING_BLOCK_RE.sub("", content).strip()


class ReasoningMarkupStreamFilter:
    """
    Buffers streamed text fragments and withholds an opening
    `<think>`/`<reasoning>` marker through its matching closing tag,
    releasing everything else - including genuine answer text that
    follows a closed reasoning block, in the very same turn -
    immediately so it keeps streaming live.

    Unlike `stream_filter.ToolMarkupStreamFilter` (which, correctly
    for leaked *tool-call* markup, suppresses everything for the rest
    of the turn once confirmed, since the remainder really is
    template noise), a reasoning block is finite and self-closing:
    real answer text routinely follows `</think>` in the very same
    response, so suppression must resume normal streaming once the
    block closes rather than suppressing for the rest of the turn.

    One instance is scoped to a single streamed turn, exactly like
    `ToolMarkupStreamFilter`.
    """

    def __init__(self, hints: tuple[str, ...] = REASONING_MARKUP_HINTS) -> None:
        self._hints = hints
        self._buffer = ""
        self._in_block = False
        self._active_closing_tag: str | None = None

    def feed(self, fragment: str) -> str:
        """
        Feed one raw streamed fragment.

        Returns:
            The portion of buffered text now safe to forward
            downstream, immediately - empty while inside an unclosed
            reasoning block, or while the buffered tail could still
            be the start of one.
        """

        if not fragment:
            return ""

        self._buffer += fragment
        output: list[str] = []

        while True:
            if self._in_block:
                assert self._active_closing_tag is not None
                close_index = self._buffer.find(self._active_closing_tag)

                if close_index == -1:
                    # Still inside the block; nothing genuine to
                    # release yet, and the buffered content itself is
                    # discarded once the block eventually closes (or
                    # the turn ends unterminated - see `flush()`).
                    break

                self._buffer = self._buffer[
                    close_index + len(self._active_closing_tag):
                ]
                self._in_block = False
                self._active_closing_tag = None
                continue

            hint_start, matched_hint = self._earliest_hint_start()

            if hint_start is None:
                safe_length = len(self._buffer) - self._longest_partial_hint_suffix()
                output.append(self._buffer[:safe_length])
                self._buffer = self._buffer[safe_length:]
                break

            output.append(self._buffer[:hint_start])
            assert matched_hint is not None
            self._buffer = self._buffer[hint_start + len(matched_hint):]
            self._in_block = True
            self._active_closing_tag = _CLOSING_TAGS[matched_hint]

        return "".join(output)

    def flush(self) -> str:
        """
        Release any text withheld as a potential opening-marker
        prefix that never actually completed into one by the end of
        the turn.

        An unterminated (opened but never closed) reasoning block at
        the end of the turn - e.g. a truncated generation - is
        discarded entirely, exactly like `strip_reasoning_markup()`'s
        equivalent handling of the final accumulated content.
        """

        if self._in_block:
            return ""

        residual = self._buffer
        self._buffer = ""

        return residual

    def _earliest_hint_start(self) -> tuple[int | None, str | None]:
        earliest: int | None = None
        matched: str | None = None

        for hint in self._hints:
            index = self._buffer.find(hint)

            if index != -1 and (earliest is None or index < earliest):
                earliest = index
                matched = hint

        return earliest, matched

    def _longest_partial_hint_suffix(self) -> int:
        longest = 0

        for hint in self._hints:
            max_check = min(len(hint) - 1, len(self._buffer))

            for length in range(max_check, 0, -1):
                if self._buffer.endswith(hint[:length]):
                    longest = max(longest, length)
                    break

        return longest
