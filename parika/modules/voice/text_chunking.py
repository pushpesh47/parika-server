"""
PARIKA Voice Module - Text Chunking

Splits a full text-to-speech response into small, bounded chunks so
`driver_tts.py` can synthesize one chunk at a time and check for
cancellation between chunks -- the mechanism that makes "Stop
Speaking" (see `operation_registry.py`) take effect mid-response
rather than only after synthesizing the entire response.

Deliberately simple, deterministic, sentence-aware splitting -- no AI
call, no third-party dependency. Never produces an empty chunk.
"""

from __future__ import annotations

import re

_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")


def split_into_speech_chunks(
    text: str,
    *,
    max_characters: int,
) -> tuple[str, ...]:
    """
    Split `text` into an ordered tuple of non-empty chunks, each at
    most `max_characters` long where possible.

    Splits first on sentence boundaries (after `.`/`!`/`?` followed by
    whitespace); a single sentence longer than `max_characters` is
    further split on word boundaries so no chunk-building loop ever
    stalls on one oversized sentence.
    """

    normalized = " ".join(text.split())

    if not normalized:
        return ()

    if max_characters <= 0:
        return (normalized,)

    sentences = _SENTENCE_BOUNDARY_PATTERN.split(normalized)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        for piece in _bounded_pieces(sentence, max_characters=max_characters):
            candidate = f"{current} {piece}".strip() if current else piece

            if len(candidate) <= max_characters:
                current = candidate
                continue

            if current:
                chunks.append(current)

            current = piece

    if current:
        chunks.append(current)

    return tuple(chunks)


def _bounded_pieces(sentence: str, *, max_characters: int) -> tuple[str, ...]:
    """
    Split one sentence into word-bounded pieces no longer than
    `max_characters`, so an oversized sentence never produces one
    unbounded chunk.
    """

    sentence = sentence.strip()

    if not sentence:
        return ()

    if len(sentence) <= max_characters:
        return (sentence,)

    words = sentence.split(" ")
    pieces: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip() if current else word

        if len(candidate) <= max_characters:
            current = candidate
            continue

        if current:
            pieces.append(current)

        current = word

    if current:
        pieces.append(current)

    return tuple(pieces)
