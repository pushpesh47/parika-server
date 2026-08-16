"""
Unit tests for `structured_facts.extract_slot()`/`render_structured_content()`
-- the deterministic slot-extraction rules `remember()` uses to satisfy
the PARIKA Memory Subsystem Refactor's Semantic Merge requirement.
"""

from __future__ import annotations

from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.structured_facts import (
    extract_slot,
    render_structured_content,
)


class TestExtractSlot:
    def test_recognizes_name(self) -> None:
        match = extract_slot("My name is Pushpesh.")

        assert match is not None
        assert match.group_key == "profile"
        assert match.slot_name == "Name"
        assert match.value == "Pushpesh"
        assert match.category is MemoryCategory.PROFILE

    def test_recognizes_nickname(self) -> None:
        match = extract_slot("My nickname is Push.")

        assert match is not None
        assert match.group_key == "profile"
        assert match.slot_name == "Nickname"
        assert match.value == "Push"

    def test_recognizes_preferred_language_statement(self) -> None:
        match = extract_slot("My preferred language is Python 3.14.")

        assert match is not None
        assert match.group_key == "programming_preferences"
        assert match.slot_name == "Language"
        assert match.value == "Python 3.14"

    def test_recognizes_framework_from_i_use(self) -> None:
        match = extract_slot("I use Laravel.")

        assert match is not None
        assert match.group_key == "programming_preferences"
        assert match.slot_name == "Framework"
        assert match.value == "Laravel"

    def test_recognizes_language_from_i_like(self) -> None:
        match = extract_slot("I like Python.")

        assert match is not None
        assert match.slot_name == "Language"
        assert match.value == "Python"

    def test_recognizes_preferred_transport(self) -> None:
        match = extract_slot("I prefer trains.")

        assert match is not None
        assert match.group_key == "travel_preferences"
        assert match.slot_name == "Preferred transport"
        assert match.value == "Train"

    def test_recognizes_preferred_seat(self) -> None:
        match = extract_slot("I prefer window seats.")

        assert match is not None
        assert match.group_key == "travel_preferences"
        assert match.slot_name == "Preferred seat"
        assert match.value == "Window"

    def test_unrelated_content_matches_nothing(self) -> None:
        assert extract_slot("I like pizza.") is None
        assert extract_slot("I prefer dark mode.") is None
        assert extract_slot("The sky is blue.") is None
        assert extract_slot("I use a MacBook.") is None


class TestRenderStructuredContent:
    def test_renders_title_and_slots_in_order(self) -> None:
        rendered = render_structured_content(
            "Profile", {"Name": "Pushpesh Sharma", "Nickname": "Push"}
        )

        assert rendered == (
            "Profile\n\nName:\nPushpesh Sharma\n\nNickname:\nPush"
        )
