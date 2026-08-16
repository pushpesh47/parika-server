"""
Unit tests for the Core Semantic Vocabulary (`parika.core.semantics.vocabulary`).
"""

from __future__ import annotations

from parika.core.semantics.vocabulary import CANONICAL_CONCEPTS, normalize


class TestCanonicalConcepts:
    def test_includes_well_known_concepts(self) -> None:
        assert "general_chat" in CANONICAL_CONCEPTS
        assert "coding" in CANONICAL_CONCEPTS
        assert "reasoning" in CANONICAL_CONCEPTS
        assert "ocr" in CANONICAL_CONCEPTS
        assert "document_understanding" in CANONICAL_CONCEPTS
        assert "vision_understanding" in CANONICAL_CONCEPTS
        assert "image_generation" in CANONICAL_CONCEPTS
        assert "speech_to_text" in CANONICAL_CONCEPTS
        assert "tool_use" in CANONICAL_CONCEPTS


class TestNormalize:
    def test_canonical_value_passes_through_unchanged(self) -> None:
        assert normalize("general_chat") == "general_chat"
        assert normalize("ocr") == "ocr"

    def test_known_alias_normalizes_to_canonical(self) -> None:
        assert normalize("chat") == "general_chat"
        assert normalize("vision") == "vision_understanding"
        assert normalize("function_calling") == "tool_use"

    def test_unknown_value_passes_through_unchanged(self) -> None:
        assert normalize("some_future_concept") == "some_future_concept"

    def test_empty_string_passes_through_unchanged(self) -> None:
        assert normalize("") == ""
