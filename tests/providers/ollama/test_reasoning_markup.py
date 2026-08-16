"""
Unit tests for `parika.providers.ollama.reasoning_markup`.
"""

from __future__ import annotations

from parika.providers.ollama.reasoning_markup import (
    REASONING_MARKUP_HINTS,
    strip_reasoning_markup,
)


class TestStripReasoningMarkup:
    def test_removes_think_block(self) -> None:
        content = (
            "<think>I need to search for that.</think>"
            "The answer is 42."
        )

        assert strip_reasoning_markup(content) == "The answer is 42."

    def test_removes_reasoning_block(self) -> None:
        content = (
            "<reasoning>Let me check the docs.</reasoning>"
            "It is documented in section 3."
        )

        assert strip_reasoning_markup(content) == (
            "It is documented in section 3."
        )

    def test_removes_leading_and_trailing_whitespace_left_behind(
        self,
    ) -> None:
        content = "<think>Hmm.</think>\n\nFinal answer."

        assert strip_reasoning_markup(content) == "Final answer."

    def test_unterminated_block_is_removed_to_end_of_string(self) -> None:
        """
        A stream cut off mid-reasoning-block (e.g. truncated
        generation) must never leak the dangling, unterminated
        fragment as if it were the answer.
        """

        content = "<think>Still thinking about this one"

        assert strip_reasoning_markup(content) == ""

    def test_ordinary_content_is_unchanged(self) -> None:
        content = "The sky is blue because of Rayleigh scattering."

        assert strip_reasoning_markup(content) == content

    def test_empty_content_is_unchanged(self) -> None:
        assert strip_reasoning_markup("") == ""

    def test_case_insensitive(self) -> None:
        content = "<THINK>internal</THINK>Visible answer."

        assert strip_reasoning_markup(content) == "Visible answer."

    def test_hints_are_the_structural_markers_only(self) -> None:
        """
        Documents the design contract: hints are structural tags, not
        natural-language phrases - never "I need to search" or
        similar wording.
        """

        assert REASONING_MARKUP_HINTS == ("<think>", "<reasoning>")
