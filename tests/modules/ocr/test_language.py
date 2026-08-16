"""
Unit tests for the OCR Module's deterministic language detection
(`parika.modules.ocr.language`). Uses the real `langdetect` dependency
- never a Provider, never Brain/Goal.
"""

from __future__ import annotations

from parika.modules.ocr.language import detect_language


class TestDetectLanguage:
    def test_detects_english_text(self) -> None:
        result = detect_language(
            "This is a perfectly ordinary English sentence for testing."
        )

        assert result.detected
        assert result.language == "en"
        assert 0.0 < result.confidence <= 1.0
        assert result.candidates
        assert result.candidates[0].language == "en"

    def test_detects_french_text(self) -> None:
        result = detect_language(
            "Bonjour, comment allez-vous aujourd'hui mon ami de longue date?"
        )

        assert result.detected
        assert result.language == "fr"

    def test_empty_text_is_not_detected_and_does_not_raise(self) -> None:
        result = detect_language("   ")

        assert not result.detected
        assert result.language is None
        assert result.confidence == 0.0
        assert result.candidates == ()

    def test_repeated_calls_on_the_same_text_are_deterministic(self) -> None:
        text = "short ambiguous text"

        first = detect_language(text)
        second = detect_language(text)

        assert first.language == second.language
        assert first.confidence == second.confidence
