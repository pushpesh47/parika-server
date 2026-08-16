"""
Unit tests for PARIKA Model Knowledge
(`parika.core.semantics.model_knowledge`).
"""

from __future__ import annotations

from parika.core.semantics.model_knowledge import (
    ModelKnowledgeEntry,
    SpecializationOverride,
    get_model_knowledge,
    get_override,
)


class TestGetOverride:
    def test_returns_none_for_unregistered_model(self) -> None:
        assert get_override("qwen3-coder-next:latest") is None

    def test_returns_curated_override_for_glm_ocr(self) -> None:
        override = get_override("glm-ocr:latest")

        assert override is not None
        assert override.remove == frozenset({"general_chat"})
        assert override.add == frozenset({"ocr", "document_understanding"})

    def test_matches_regardless_of_tag_suffix(self) -> None:
        assert get_override("glm-ocr:latest") == get_override("glm-ocr:q4_0")
        assert get_override("glm-ocr") == get_override("glm-ocr:latest")

    def test_matches_case_insensitively(self) -> None:
        assert get_override("GLM-OCR:LATEST") == get_override("glm-ocr:latest")

    def test_override_defaults_are_empty(self) -> None:
        override = SpecializationOverride()

        assert override.remove == frozenset()
        assert override.add == frozenset()

    def test_returns_curated_override_for_minicpm_v4_5(self) -> None:
        override = get_override("minicpm-v4.5:latest")

        assert override is not None
        assert override.remove == frozenset({"general_chat"})
        assert override.add == frozenset(
            {"vision_understanding", "ocr", "document_understanding"}
        )


class TestGetModelKnowledge:
    def test_returns_none_for_unregistered_model(self) -> None:
        assert get_model_knowledge("qwen3-coder-next:latest") is None

    def test_returns_observed_knowledge_for_glm_ocr(self) -> None:
        entry = get_model_knowledge("glm-ocr:latest")

        assert entry is not None
        assert entry.strengths == frozenset({"ocr", "document_understanding"})

    def test_returns_observed_knowledge_for_minicpm_v4_5(self) -> None:
        entry = get_model_knowledge("minicpm-v4.5:latest")

        assert entry is not None
        assert entry.strengths == frozenset(
            {"ocr", "document_understanding", "ui_analysis", "chart_analysis"}
        )

    def test_matches_regardless_of_tag_suffix(self) -> None:
        assert get_model_knowledge("glm-ocr:latest") == get_model_knowledge(
            "glm-ocr:q4_0"
        )

    def test_matches_case_insensitively(self) -> None:
        assert get_model_knowledge("GLM-OCR:LATEST") == get_model_knowledge(
            "glm-ocr:latest"
        )

    def test_entry_defaults_are_empty(self) -> None:
        entry = ModelKnowledgeEntry()

        assert entry.strengths == frozenset()
        assert entry.notes == ""

    def test_knowledge_is_independent_from_specialization_override(self) -> None:
        # PARIKA Model Knowledge is a separate concept from the Local
        # Curated Override: a model may have one without the other,
        # and neither table drives the other.
        assert get_override("qwen3-coder-next:latest") is None
        assert get_model_knowledge("qwen3-coder-next:latest") is None
