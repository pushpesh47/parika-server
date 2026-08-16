"""
PARIKA Web Search Tool - HTML Extraction

Provides dependency-free extraction of a page title, meta
description, and readable text content from raw HTML using only the
Python standard library's `html.parser`.
"""

from __future__ import annotations

from html.parser import HTMLParser

_SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template"})


class _MetadataParser(HTMLParser):
    """
    Extracts the `<title>` text and the `<meta name="description">`
    content from an HTML document.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self.title: str | None = None
        self.description: str | None = None

        self._in_title = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:

        if tag == "title" and self.title is None:
            self._in_title = True
            return

        if tag == "meta" and self.description is None:
            attributes = dict(attrs)
            name = (attributes.get("name") or "").lower()
            property_name = (attributes.get("property") or "").lower()

            if name == "description" or property_name == "og:description":
                content = attributes.get("content")

                if content:
                    self.description = content.strip()

    def handle_endtag(self, tag: str) -> None:

        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:

        if self._in_title and self.title is None:
            stripped = data.strip()

            if stripped:
                self.title = stripped


class _TextExtractor(HTMLParser):
    """
    Extracts visible text content from an HTML document, skipping
    script, style, and other non-visible content.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:

        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:

        if tag in _SKIPPED_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:

        if self._skip_depth > 0:
            return

        stripped = data.strip()

        if stripped:
            self._chunks.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._chunks)


def extract_title(html: str) -> str | None:
    """
    Extract the `<title>` text from an HTML document.

    Returns:
        The title text, or None if no title was found.
    """

    parser = _MetadataParser()
    parser.feed(html)
    parser.close()

    return parser.title


def extract_meta_description(html: str) -> str | None:
    """
    Extract the meta description from an HTML document.

    Returns:
        The description text, or None if none was found.
    """

    parser = _MetadataParser()
    parser.feed(html)
    parser.close()

    return parser.description


def extract_text(html: str) -> str:
    """
    Extract visible, whitespace-normalized text content from an HTML
    document.

    Script, style, and other non-visible elements are excluded.
    """

    parser = _TextExtractor()
    parser.feed(html)
    parser.close()

    return parser.get_text()
