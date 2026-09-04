"""
PARIKA Voice Module - TTS Text Sanitization

Converts LLM output (which may contain Markdown and other formatting
intended for visual presentation) into clean text suitable for speech
synthesis. The goal is to speak semantic content, not markup syntax.

This module is provider-independent and runs before text reaches the
TTS engine. It is deliberately conservative: it removes formatting
artifacts while preserving meaningful punctuation and content.

Processing order (each step operates on the output of the previous):
1. Code blocks (```...```) -> extract content or replace with placeholder
2. Inline code (`...`) -> remove backticks
3. Links ([text](url)) -> keep link text, optionally announce URL
4. Headings (# ...) -> remove # markers
5. Emphasis (**bold**, *italic*, __bold__, _italic_) -> remove markers
6. Bullets (- item, * item) -> remove bullet markers
8. Horizontal rules (---, ***) -> remove
9. Blockquotes (> text) -> remove > markers
10. Normalize whitespace
"""

from __future__ import annotations

import re

# Pattern for fenced code blocks: ```lang\ncontent\n```
_CODE_BLOCK_PATTERN = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)\n```", re.DOTALL)

# Pattern for inline code: `code` (but not standalone backticks)
_INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+?)`")

# Pattern for links: [text](url) - capture text and optionally url
_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")

# Pattern for images: ![alt](url) - keep alt text
_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]+\)")

# Pattern for headings: # Heading, ## Heading, etc.
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# Pattern for bold: **text** or __text__
_BOLD_PATTERN = re.compile(r"(\*\*|__)(.+?)\1")

# Pattern for italic: *text* or _text_ (but not already handled by bold)
_ITALIC_PATTERN = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)|(?<!_)_([^_\n]+?)_(?!_)")

# Pattern for strikethrough: ~~text~~
_STRIKETHROUGH_PATTERN = re.compile(r"~~(.+?)~~")

# Pattern for bullet points at start of line: - item, * item, + item
_BULLET_PATTERN = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)

# Pattern for numbered lists: 1. item, 2. item
_NUMBERED_LIST_PATTERN = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)

# Pattern for horizontal rules: ---, ***, ___
_HORIZONTAL_RULE_PATTERN = re.compile(r"^[\s]*([-*_])\1{2,}[\s]*$", re.MULTILINE)

# Pattern for blockquotes: > text
_BLOCKQUOTE_PATTERN = re.compile(r"^[\s]*>\s?", re.MULTILINE)

# Pattern for multiple consecutive newlines
_MULTIPLE_NEWLINES_PATTERN = re.compile(r"\n{3,}")

# Pattern for multiple spaces
_MULTIPLE_SPACES_PATTERN = re.compile(r"[ \t]{2,}")


def sanitize_for_tts(text: str) -> str:
    """
    Sanitize text for TTS synthesis.

    Removes Markdown formatting artifacts while preserving semantic
    content and meaningful punctuation.

    Args:
        text: Raw text potentially containing Markdown formatting.

    Returns:
        Clean text suitable for speech synthesis.
    """
    if not text or not text.strip():
        return ""

    # 1. Handle code blocks - extract content (could be long, so just note it)
    def _code_block_repl(match: re.Match) -> str:
        content = match.group(1).strip()
        if content:
            # For TTS, we could say "code block" or just read the content
            # Here we keep the content but prefix with a marker
            return f"Code block: {content}"
        return "Empty code block"

    text = _CODE_BLOCK_PATTERN.sub(_code_block_repl, text)

    # 2. Handle inline code - remove backticks, keep content
    text = _INLINE_CODE_PATTERN.sub(r"\1", text)

    # 3. Handle images - keep alt text
    text = _IMAGE_PATTERN.sub(r"\1", text)

    # 4. Handle links - keep link text, optionally append URL for context
    def _link_repl(match: re.Match) -> str:
        link_text = match.group(1)
        return link_text

    text = _LINK_PATTERN.sub(_link_repl, text)

    # 5. Handle headings - remove # markers
    text = _HEADING_PATTERN.sub("", text)

    # 6. Handle bold - remove markers
    text = _BOLD_PATTERN.sub(r"\2", text)

    # 7. Handle italic - remove markers
    def _italic_repl(match: re.Match) -> str:
        return match.group(1) or match.group(2) or ""

    text = _ITALIC_PATTERN.sub(_italic_repl, text)

    # 8. Handle strikethrough - remove markers
    text = _STRIKETHROUGH_PATTERN.sub(r"\1", text)

    # 9. Handle bullets - remove bullet markers
    text = _BULLET_PATTERN.sub("", text)

    # 10. Handle numbered lists - remove numbering
    text = _NUMBERED_LIST_PATTERN.sub("", text)

    # 11. Handle horizontal rules - remove
    text = _HORIZONTAL_RULE_PATTERN.sub("", text)

    # 12. Handle blockquotes - remove > markers
    text = _BLOCKQUOTE_PATTERN.sub("", text)

    # 13. Normalize whitespace
    # Replace multiple newlines with double newline (paragraph break)
    text = _MULTIPLE_NEWLINES_PATTERN.sub("\n\n", text)
    # Replace multiple spaces/tabs with single space
    text = _MULTIPLE_SPACES_PATTERN.sub(" ", text)
    # Trim each line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


def sanitize_for_tts_preserving_links(text: str, *, announce_urls: bool = False) -> str:
    """
    Sanitize text for TTS with configurable link handling.

    Args:
        text: Raw text potentially containing Markdown formatting.
        announce_urls: If True, append the URL after link text
                       (e.g., "OpenAI https://openai.com").

    Returns:
        Clean text suitable for speech synthesis.
    """
    if not text or not text.strip():
        return ""

    # 1. Handle code blocks
    def _code_block_repl(match: re.Match) -> str:
        content = match.group(1).strip()
        if content:
            return f"Code block: {content}"
        return "Empty code block"

    text = _CODE_BLOCK_PATTERN.sub(_code_block_repl, text)

    # 2. Handle inline code
    text = _INLINE_CODE_PATTERN.sub(r"\1", text)

    # 3. Handle images
    text = _IMAGE_PATTERN.sub(r"\1", text)

    # 4. Handle links with configurable URL announcement
    def _link_repl(match: re.Match) -> str:
        link_text = match.group(1)
        if announce_urls:
            # Extract URL from the full match
            full_match = match.group(0)
            url_match = re.search(r"\(([^)]+)\)", full_match)
            if url_match:
                return f"{link_text} {url_match.group(1)}"
        return link_text

    text = _LINK_PATTERN.sub(_link_repl, text)

    # 5-12. Same as basic sanitize
    def _italic_repl(match: re.Match) -> str:
        return match.group(1) or match.group(2) or ""

    text = _HEADING_PATTERN.sub("", text)
    text = _BOLD_PATTERN.sub(r"\2", text)
    text = _ITALIC_PATTERN.sub(_italic_repl, text)
    text = _STRIKETHROUGH_PATTERN.sub(r"\1", text)
    text = _BULLET_PATTERN.sub("", text)
    text = _NUMBERED_LIST_PATTERN.sub("", text)
    text = _HORIZONTAL_RULE_PATTERN.sub("", text)
    text = _BLOCKQUOTE_PATTERN.sub("", text)

    # 13. Normalize whitespace
    text = _MULTIPLE_NEWLINES_PATTERN.sub("\n\n", text)
    text = _MULTIPLE_SPACES_PATTERN.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()