"""
Unit tests for `parika.interfaces.ai_context.model_selection_policy`.
"""

from __future__ import annotations

from parika.interfaces.ai_context.model_selection_policy import (
    build_model_selection_policy_text,
)


class TestBuildModelSelectionPolicyText:
    def test_mentions_the_reserved_argument_name(self) -> None:
        text = build_model_selection_policy_text()

        assert "model_selection_hint" in text

    def test_mentions_candidate_models_and_confidence(self) -> None:
        text = build_model_selection_policy_text()

        assert "candidate_models" in text
        assert "confidence" in text

    def test_mentions_reasoning_level(self) -> None:
        text = build_model_selection_policy_text()

        assert "reasoning_level" in text
        assert "simple" in text
        assert "complex" in text

    def test_states_the_hint_is_optional(self) -> None:
        text = build_model_selection_policy_text().lower()

        assert "optional" in text

    def test_never_mentions_a_specific_capability_or_model_name(self) -> None:
        text = build_model_selection_policy_text().lower()

        # Capability Independence: this policy must remain completely
        # generic (see the module docstring and `reasoning_policy.py`'s
        # own precedent).
        for forbidden in (
            "vision.provider_describe_image",
            "ocr.provider_extract_text",
            "minicpm",
            "qwen",
        ):
            assert forbidden not in text

    def test_is_a_pure_function(self) -> None:
        assert build_model_selection_policy_text() == build_model_selection_policy_text()
