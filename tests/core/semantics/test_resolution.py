"""
Unit tests for Semantic Profile Resolution
(`parika.core.semantics.resolution`).

Covers the exact bug this package was built to fix: Ollama's
`"completion"` capability causing an OCR-specialized model (`glm-ocr`)
to be mis-classified as `"general_chat"`.
"""

from __future__ import annotations

from parika.core.semantics.resolution import resolve_specializations


class TestResolveSpecializationsWithoutOverride:
    def test_normalizes_provider_reported_values(self) -> None:
        resolved = resolve_specializations(
            "some-model:latest",
            {"chat", "function_calling"},
        )

        assert resolved == {"general_chat", "tool_use"}

    def test_passes_through_when_already_canonical(self) -> None:
        resolved = resolve_specializations("some-model:latest", {"coding"})

        assert resolved == {"coding"}

    def test_empty_provider_evidence_resolves_to_empty(self) -> None:
        assert resolve_specializations("some-model:latest", frozenset()) == frozenset()


class TestResolveSpecializationsWithOverride:
    def test_glm_ocr_override_removes_general_chat_and_adds_ocr(self) -> None:
        # This is exactly what Ollama's Provider Metadata evidence
        # source reports for glm-ocr today: "completion" -> "general_chat".
        resolved = resolve_specializations("glm-ocr:latest", {"general_chat"})

        assert resolved == {"ocr", "document_understanding"}
        assert "general_chat" not in resolved

    def test_override_add_wins_even_if_not_provider_reported(self) -> None:
        resolved = resolve_specializations("glm-ocr:latest", frozenset())

        assert resolved == {"ocr", "document_understanding"}

    def test_override_remove_only_strips_matching_values(self) -> None:
        # Any other provider-reported evidence survives the override
        # untouched; only "general_chat" is removed for glm-ocr.
        resolved = resolve_specializations(
            "glm-ocr:latest",
            {"general_chat", "reasoning"},
        )

        assert resolved == {"reasoning", "ocr", "document_understanding"}

    def test_minicpm_v4_5_override_adds_vision_understanding(self) -> None:
        # This is exactly what Ollama's Provider Metadata evidence
        # source reports for minicpm-v4.5 today: "completion" ->
        # "general_chat" (its "vision" capability is deliberately
        # left unmapped to a specialization -- see
        # `parika.providers.ollama.model_mapping`'s own docstring).
        resolved = resolve_specializations("minicpm-v4.5:latest", {"general_chat"})

        assert resolved == {"vision_understanding", "ocr", "document_understanding"}
        assert "general_chat" not in resolved
