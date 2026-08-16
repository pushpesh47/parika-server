"""
PARIKA OCR Module - Deterministic Text Layout Analysis

Pure, stateless heuristics over already-recognized plain text - never
a model call, never a Brain/Goal/Capability concept. Used by
`text_tools_driver.py`'s `ocr.extract_layout`, and directly answers
several of the OCR extension's "Analysis Features": character count,
word count, paragraph count, and reading order.

Deliberately text-only: without a spatial OCR engine (word-level
bounding boxes/coordinates), true column detection and a fully
reliable reading order cannot be recovered after the fact - the
"reading order" this module reports is simply the text's own top-to-
bottom order, never reordered, which is correct for single-column
text and not verifiable for multi-column layouts from plain text
alone. Line and paragraph segmentation are reliable, well-understood
heuristics; heading detection specifically targets the common
typographic convention of a short, isolated (blank-line-separated)
title line immediately preceding a longer paragraph - it will not
find a heading that runs directly into its body paragraph with no
blank line, which is an intentional, documented scope limit rather
than a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

_MAX_HEADING_LENGTH = 70


@dataclass(frozen=True, slots=True, kw_only=True)
class TextLayout:
    """Result of `build_text_layout()` - see its docstring."""

    lines: tuple[str, ...]
    paragraphs: tuple[str, ...]
    headings: tuple[str, ...]
    word_count: int
    character_count: int


def build_text_layout(text: str) -> TextLayout:
    """
    Segment already-recognized `text` into lines, paragraphs, and a
    best-effort list of probable headings, preserving the text's own
    top-to-bottom reading order throughout (never reordered).
    """

    lines = tuple(line.strip() for line in text.splitlines() if line.strip())
    groups = _group_paragraphs(text)
    paragraphs = tuple(" ".join(group) for group in groups)
    headings = _detect_headings(groups)

    return TextLayout(
        lines=lines,
        paragraphs=paragraphs,
        headings=headings,
        word_count=len(text.split()),
        character_count=len(text),
    )


def _group_paragraphs(text: str) -> tuple[tuple[str, ...], ...]:
    """Blank-line-separated groups of stripped lines, preserving order."""

    groups: list[list[str]] = []
    current: list[str] = []

    for line in text.splitlines():
        if line.strip():
            current.append(line.strip())
        elif current:
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    return tuple(tuple(group) for group in groups)


def _detect_headings(groups: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    """
    A single-line paragraph group is a probable heading when it is
    short, carries no terminal sentence punctuation, is upper-case or
    title-case, and is immediately followed by a longer paragraph -
    see this module's own docstring for this heuristic's documented
    scope limits.
    """

    headings: list[str] = []

    for index, group in enumerate(groups):
        if len(group) != 1:
            continue

        candidate = group[0]
        is_short = len(candidate) <= _MAX_HEADING_LENGTH
        has_no_terminal_punctuation = not candidate.endswith((".", ",", ";"))
        is_heading_like = candidate.isupper() or candidate.istitle()
        has_following_paragraph = index + 1 < len(groups) and len(
            " ".join(groups[index + 1])
        ) > len(candidate)

        if (
            is_short
            and has_no_terminal_punctuation
            and is_heading_like
            and has_following_paragraph
        ):
            headings.append(candidate)

    return tuple(headings)
