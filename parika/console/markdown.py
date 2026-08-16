"""
PARIKA Console - Markdown Rendering

A small, dependency-free Markdown-to-ANSI renderer for terminal
output.

Supports the subset of Markdown that a chat model's responses
realistically use: headings, bullet lists, fenced code blocks, and
inline bold/italic/code spans. This is intentionally not a complete
CommonMark implementation; it is a presentation-only helper for the
Console, matching the project's standard-library-first preference
over adding a Markdown rendering dependency.
"""

from __future__ import annotations

import re

from .colors import Ansi, colorize

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^([-*+])\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\d+[.)])\s+(.*)$")
_CODE_FENCE_RE = re.compile(r"^```")

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)([^*]+?)\*(?!\*)")


def render_markdown(text: str, *, color: bool = True) -> str:
    """
    Render Markdown-flavored text for display in an ANSI terminal.

    Args:
        text:
            Markdown-flavored source text.

        color:
            Whether to emit ANSI color codes. Pass False when output
            is not a TTY.

    Returns:
        Rendered text ready to be written directly to the terminal.
    """

    lines = text.split("\n")
    rendered_lines: list[str] = []

    in_code_block = False
    code_block_lines: list[str] = []

    for line in lines:
        if _CODE_FENCE_RE.match(line.strip()):
            if in_code_block:
                rendered_lines.append(
                    _render_code_block(code_block_lines, color=color)
                )
                code_block_lines = []
                in_code_block = False
            else:
                in_code_block = True

            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        rendered_lines.append(_render_line(line, color=color))

    if in_code_block and code_block_lines:
        rendered_lines.append(
            _render_code_block(code_block_lines, color=color)
        )

    return "\n".join(rendered_lines)


def _render_line(line: str, *, color: bool) -> str:
    """
    Render a single non-code-block Markdown line.
    """

    stripped = line.strip()

    heading_match = _HEADING_RE.match(stripped)

    if heading_match:
        content = _render_inline(heading_match.group(2), color=color)
        return colorize(content, Ansi.BOLD + Ansi.CYAN, enabled=color)

    bullet_match = _BULLET_RE.match(stripped)

    if bullet_match:
        content = _render_inline(bullet_match.group(2), color=color)
        return f"  - {content}"

    ordered_match = _ORDERED_RE.match(stripped)

    if ordered_match:
        content = _render_inline(ordered_match.group(2), color=color)
        return f"  {ordered_match.group(1)} {content}"

    return _render_inline(line, color=color)


def _render_inline(text: str, *, color: bool) -> str:
    """
    Render inline bold/italic/code spans within a single line.
    """

    def _bold(match: re.Match[str]) -> str:
        return colorize(match.group(1), Ansi.BOLD, enabled=color)

    def _code(match: re.Match[str]) -> str:
        return colorize(match.group(1), Ansi.YELLOW, enabled=color)

    def _italic(match: re.Match[str]) -> str:
        return colorize(match.group(1), Ansi.ITALIC, enabled=color)

    text = _BOLD_RE.sub(_bold, text)
    text = _INLINE_CODE_RE.sub(_code, text)
    text = _ITALIC_RE.sub(_italic, text)

    return text


def _render_code_block(lines: list[str], *, color: bool) -> str:
    """
    Render a fenced code block.
    """

    joined = "\n".join(lines)

    return colorize(joined, Ansi.GREEN, enabled=color)
