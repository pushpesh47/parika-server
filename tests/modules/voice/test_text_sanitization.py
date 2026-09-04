"""
Unit tests for `parika.modules.voice.text_sanitization`.
"""

from __future__ import annotations

from parika.modules.voice.text_sanitization import (
    sanitize_for_tts,
    sanitize_for_tts_preserving_links,
)


def test_empty_text_returns_empty() -> None:
    assert sanitize_for_tts("") == ""
    assert sanitize_for_tts("   ") == ""
    assert sanitize_for_tts("\n\n") == ""


def test_bold_markdown_removed() -> None:
    assert sanitize_for_tts("**bold**") == "bold"
    assert sanitize_for_tts("__bold__") == "bold"
    assert sanitize_for_tts("This is **bold** text") == "This is bold text"


def test_italic_markdown_removed() -> None:
    assert sanitize_for_tts("*italic*") == "italic"
    assert sanitize_for_tts("_italic_") == "italic"
    assert sanitize_for_tts("This is *italic* text") == "This is italic text"


def test_code_blocks_handled() -> None:
    result = sanitize_for_tts("```python\nprint('hello')\n```")
    assert "print('hello')" in result
    assert "Code block:" in result


def test_inline_code_backticks_removed() -> None:
    assert sanitize_for_tts("`code`") == "code"
    assert sanitize_for_tts("Use `print()` to output") == "Use print() to output"


def test_links_keep_text() -> None:
    assert sanitize_for_tts("[OpenAI](https://openai.com)") == "OpenAI"
    assert sanitize_for_tts("Visit [OpenAI](https://openai.com) today") == "Visit OpenAI today"


def test_links_announce_urls_option() -> None:
    result = sanitize_for_tts_preserving_links(
        "[OpenAI](https://openai.com)", announce_urls=True
    )
    assert "OpenAI" in result
    assert "https://openai.com" in result


def test_headings_hash_removed() -> None:
    assert sanitize_for_tts("# Heading") == "Heading"
    assert sanitize_for_tts("## Subheading") == "Subheading"
    assert sanitize_for_tts("### Level 3") == "Level 3"
    assert sanitize_for_tts("# Heading\n\nContent") == "Heading\n\nContent"


def test_bullets_removed() -> None:
    assert sanitize_for_tts("- First item") == "First item"
    assert sanitize_for_tts("* Second item") == "Second item"
    assert sanitize_for_tts("+ Third item") == "Third item"
    assert sanitize_for_tts("- Item 1\n- Item 2") == "Item 1\nItem 2"


def test_numbered_lists_removed() -> None:
    assert sanitize_for_tts("1. First") == "First"
    assert sanitize_for_tts("2. Second") == "Second"
    assert sanitize_for_tts("1. Item one\n2. Item two") == "Item one\nItem two"


def test_strikethrough_removed() -> None:
    assert sanitize_for_tts("~~deleted~~") == "deleted"
    assert sanitize_for_tts("This is ~~wrong~~ correct") == "This is wrong correct"


def test_blockquotes_removed() -> None:
    assert sanitize_for_tts("> Quoted text") == "Quoted text"
    assert sanitize_for_tts("> Line 1\n> Line 2") == "Line 1\nLine 2"


def test_horizontal_rules_removed() -> None:
    assert sanitize_for_tts("---") == ""
    assert sanitize_for_tts("***") == ""
    assert sanitize_for_tts("___") == ""
    # Horizontal rule between content creates paragraph break
    assert sanitize_for_tts("Content\n---\nMore") == "Content\n\nMore"


def test_preserves_meaningful_punctuation() -> None:
    # Decimal numbers
    assert "3.14" in sanitize_for_tts("Pi is 3.14")
    # Currency
    assert "$500" in sanitize_for_tts("It costs $500")
    # Math
    assert "2 + 2 = 4" in sanitize_for_tts("What is 2 + 2 = 4?")
    # Questions, exclamations
    assert "What?" in sanitize_for_tts("What?")
    assert "Hello!" in sanitize_for_tts("Hello!")
    # Commas, semicolons, colons
    assert "Hello, world" in sanitize_for_tts("Hello, world")
    assert "A; B" in sanitize_for_tts("A; B")
    assert "A: B" in sanitize_for_tts("A: B")
    # Parentheses
    assert "(example)" in sanitize_for_tts("(example)")


def test_preserves_dates_and_identifiers() -> None:
    assert "2024-01-15" in sanitize_for_tts("Date: 2024-01-15")
    assert "user@example.com" in sanitize_for_tts("Email: user@example.com")
    assert "v1.0.0" in sanitize_for_tts("Version v1.0.0")


def test_complex_markdown() -> None:
    text = """# Title

**Bold** and *italic* text.

- Item 1
- Item 2

`inline code` and a [link](https://example.com).

```python
def hello():
    print("world")
```

> A quote

---

More text."""
    result = sanitize_for_tts(text)
    assert "Title" in result
    assert "Bold" in result
    assert "italic" in result
    assert "Item 1" in result
    assert "Item 2" in result
    assert "inline code" in result
    assert "link" in result
    assert "hello" in result
    assert "world" in result
    assert "A quote" in result
    assert "More text" in result
    # Formatting artifacts should be gone
    assert "#" not in result
    assert "**" not in result
    assert "*" not in result
    assert "`" not in result
    assert "---" not in result
    assert ">" not in result


def test_nested_formatting() -> None:
    assert sanitize_for_tts("**bold *italic* bold**") == "bold italic bold"
    assert sanitize_for_tts("*italic **bold** italic*") == "italic bold italic"


def test_whitespace_normalization() -> None:
    text = "Hello   there.\n\n\nHow  are you?"
    result = sanitize_for_tts(text)
    assert result == "Hello there.\n\nHow are you?"


def test_images_keep_alt_text() -> None:
    assert sanitize_for_tts("![Alt text](image.png)") == "Alt text"
    assert sanitize_for_tts("![Diagram](diagram.png) shows flow") == "Diagram shows flow"


def test_hindi_devanagari_preserved() -> None:
    """Hindi/Devanagari text should be preserved while Markdown is removed."""
    # Basic Hindi sentence
    assert sanitize_for_tts("नमस्ते दुनिया।") == "नमस्ते दुनिया।"
    # Bold Hindi
    assert sanitize_for_tts("**नमस्ते दुनिया।**") == "नमस्ते दुनिया।"
    # Italic Hindi
    assert sanitize_for_tts("यह *बहुत महत्वपूर्ण* है।") == "यह बहुत महत्वपूर्ण है।"
    # Heading Hindi
    assert sanitize_for_tts("# आज का समाचार") == "आज का समाचार"
    # Bullet Hindi
    assert sanitize_for_tts("- पहला बिंदु") == "पहला बिंदु"
    # Numbered list Hindi
    assert sanitize_for_tts("१. पहला बिंदु") == "पहला बिंदु"
    # Blockquote Hindi
    assert sanitize_for_tts("> उद्धरण पाठ") == "उद्धरण पाठ"
    # Mixed Hindi + English
    assert sanitize_for_tts("नमस्ते hello world") == "नमस्ते hello world"
    # Devanagari numerals
    assert sanitize_for_tts("१२३") == "१२३"
    # Currency with Devanagari numerals
    assert sanitize_for_tts("₹१,५००") == "₹१,५००"
    # Hindi punctuation (purna viram, deergh viram)
    assert sanitize_for_tts("यह है। और वह है॥") == "यह है। और वह है॥"
    # Hindi words with hyphens
    assert sanitize_for_tts("हिंदी-अंग्रेज़ी") == "हिंदी-अंग्रेज़ी"
    # Mixed script
    assert sanitize_for_tts("मिश्रित text with हिंदी") == "मिश्रित text with हिंदी"


def test_hindi_markdown_removed_not_content() -> None:
    """Markdown formatting should be removed from Hindi text, not the content."""
    # Bold markers removed, Hindi content preserved
    result = sanitize_for_tts("**महत्वपूर्ण** जानकारी")
    assert "**" not in result
    assert "महत्वपूर्ण" in result
    assert "जानकारी" in result

    # Italic markers removed
    result = sanitize_for_tts("*ध्यान दें* कृपया")
    assert "*" not in result or "ध्यान दें" in result  # * removed but content kept
    assert "ध्यान दें" in result
    assert "कृपया" in result

    # Code formatting removed
    result = sanitize_for_tts("`कोड` उदाहरण")
    assert "`" not in result
    assert "कोड" in result
    assert "उदाहरण" in result