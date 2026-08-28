"""Unit tests for detect_preferences()."""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

from parika.interfaces.preference_detection import detect_preferences


class TestDetectPreferences:
    def test_detects_explicit_preference(self) -> None:
        matches = detect_preferences("I prefer dark mode over light mode.")

        assert len(matches) == 1
        assert "i prefer dark mode" in matches[0].lower()

    def test_detects_always_instruction(self) -> None:
        matches = detect_preferences("Always respond in French.")

        assert any("always" in m.lower() for m in matches)

    def test_detects_remember_instruction(self) -> None:
        matches = detect_preferences("Remember that I use metric units.")

        assert any("remember" in m.lower() for m in matches)

    def test_no_match_returns_empty(self) -> None:
        assert detect_preferences("What is the weather today?") == ()

    def test_deduplicates_identical_matches(self) -> None:
        matches = detect_preferences("I prefer tea. I prefer tea.")

        assert len(matches) == 1

    def test_multiple_distinct_rules_can_match_same_text(self) -> None:
        matches = detect_preferences("I prefer tea. Always use metric units.")

        assert len(matches) == 2
