"""
PARIKA Console - Streaming Output

Provides `StreamingPrinter`, a small callable that writes streamed
content fragments directly to a text stream as they arrive, giving
the CLI natural token-by-token output for streamed chat responses.
"""

from __future__ import annotations

import sys
from typing import TextIO


class StreamingPrinter:
    """
    Callable `on_token` sink that writes each fragment to a stream
    immediately, without buffering.

    Fragments are written as plain text: Markdown rendering is applied
    only to the accumulated final text (see `markdown.py`), since
    Markdown constructs such as `**bold**` cannot be rendered
    correctly one character-fragment at a time.
    """

    def __init__(
        self,
        *,
        stream: TextIO = sys.stdout,
    ) -> None:
        """
        Initialize the printer.

        Args:
            stream:
                Text stream fragments are written to.
        """

        self._stream = stream
        self._chunks: list[str] = []

    def __call__(self, fragment: str) -> None:
        """
        Write one streamed fragment.
        """

        if not fragment:
            return

        self._chunks.append(fragment)
        self._stream.write(fragment)
        self._stream.flush()

    @property
    def text(self) -> str:
        """
        The full accumulated text written so far.
        """

        return "".join(self._chunks)

    @property
    def printed_any(self) -> bool:
        """
        Whether at least one non-empty fragment has been written.
        """

        return bool(self._chunks)
