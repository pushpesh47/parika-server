"""
PARIKA Ollama Provider - Streaming Tool-Markup Filter

Some locally-hosted models (see `text_tool_calls.py`'s module
docstring - e.g. `qwen3-coder:latest`) occasionally leak their chat
template's raw tool-call markup into `message.content` as plain text
instead of populating Ollama's native `message.tool_calls` field. When
this happens during a *streamed* chat, the leaked markup would reach
the caller's `on_token` callback fragment-by-fragment, in real time,
before the driver has accumulated enough of the response to recognize
and recover it - so the raw protocol markup would flash on screen
before disappearing from the final message content.

`ToolMarkupStreamFilter` sits between the raw per-chunk fragments
`consume_chat_stream()` receives and the caller's real `on_token`,
withholding only the minimum text needed to determine whether a
leaked markup block is starting, so that:

- Ordinary assistant text keeps streaming live, with no perceptible
  delay (at most a few characters are ever held back speculatively).
- The moment leaked markup is confirmed anywhere in the buffered
  text, everything from that point to the end of the turn is
  withheld from display entirely - the user never sees provider
  protocol.
- If a suspected markup prefix never actually completes into
  recognized markup (a false alarm), the withheld text is released
  via `flush()` once the turn ends, so no genuine text is ever lost.

This is a pure text filter with no knowledge of tool calls, Brain,
Planner, or any capability: it only recognizes the same markup *shape*
hints `text_tool_calls.py` uses for its own (separate, content-level)
recovery parsing. The two are complementary: this filter controls what
is ever displayed live, while `text_tool_calls.py` continues to
recover tool calls from the full, unfiltered accumulated content
exactly as before.
"""

from __future__ import annotations

from .text_tool_calls import MARKUP_HINTS


class ToolMarkupStreamFilter:
    """
    Buffers streamed text fragments and withholds any suffix that
    could be the beginning of a recognized leaked tool-call markup
    hint, releasing everything else immediately so genuine assistant
    text keeps streaming live.

    One instance is scoped to a single streamed turn: construct a new
    instance per `/api/chat` round trip, never reused across turns,
    so suppression state never leaks from one turn into the next.
    """

    def __init__(self, hints: tuple[str, ...] = MARKUP_HINTS) -> None:
        """
        Initialize the filter.

        Args:
            hints:
                Markup shape hints to recognize. Defaults to the same
                hints `text_tool_calls.looks_like_text_tool_call()`
                uses, so streaming suppression and post-hoc recovery
                stay in agreement about what counts as leaked markup.
        """

        self._hints = hints
        self._buffer = ""
        self._suppressed = False

    def feed(self, fragment: str) -> str:
        """
        Feed one raw streamed fragment.

        Args:
            fragment:
                The next raw content fragment as received from
                Ollama, in order.

        Returns:
            The portion of buffered text now safe to forward to the
            real `on_token` callback, immediately. Empty once leaked
            markup has been confirmed for this turn, or while the
            buffered tail could still be the start of one.
        """

        if not fragment:
            return ""

        if self._suppressed:
            self._buffer += fragment
            return ""

        self._buffer += fragment

        hint_start = self._earliest_hint_start()

        if hint_start is not None:
            # Anything before the confirmed markup is genuine
            # preamble text and is released normally; the markup
            # itself, and everything after it for the rest of this
            # turn, is withheld.
            safe_text = self._buffer[:hint_start]
            self._buffer = ""
            self._suppressed = True

            return safe_text

        safe_length = len(self._buffer) - self._longest_partial_hint_suffix()
        safe_text = self._buffer[:safe_length]
        self._buffer = self._buffer[safe_length:]

        return safe_text

    def flush(self) -> str:
        """
        Release any text withheld as a *potential* markup prefix that
        never actually completed into recognized markup by the end of
        the turn.

        Call this exactly once, after the stream has fully ended.

        Returns:
            The withheld text, or an empty string when the turn ended
            with confirmed leaked markup (nothing to release - that
            text is intentionally never displayed) or with nothing
            withheld at all.
        """

        if self._suppressed:
            return ""

        residual = self._buffer
        self._buffer = ""

        return residual

    def _earliest_hint_start(self) -> int | None:
        """
        Index within the current buffer where the earliest fully
        confirmed hint begins, or `None` when no hint has fully
        appeared in the buffer yet.
        """

        earliest: int | None = None

        for hint in self._hints:
            index = self._buffer.find(hint)

            if index != -1 and (earliest is None or index < earliest):
                earliest = index

        return earliest

    def _longest_partial_hint_suffix(self) -> int:
        """
        Length of the longest suffix of the current buffer that is
        also a strict prefix of one of the recognized hints - i.e.
        text that might still grow into a full hint with more
        fragments, and must not be flushed yet.
        """

        longest = 0

        for hint in self._hints:
            max_check = min(len(hint) - 1, len(self._buffer))

            for length in range(max_check, 0, -1):
                if self._buffer.endswith(hint[:length]):
                    longest = max(longest, length)
                    break

        return longest
