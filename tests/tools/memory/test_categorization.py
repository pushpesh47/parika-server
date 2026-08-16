"""Unit tests for the deterministic memory auto-categorization heuristic."""

from __future__ import annotations

from parika.core.memory_manager.memory_category import MemoryCategory
from parika.tools.memory.categorization import categorize


class TestCategorize:
    def test_profile(self) -> None:
        assert categorize("My name is Pushpesh.") is MemoryCategory.PROFILE

    def test_preference(self) -> None:
        assert categorize("I prefer dark mode.") is MemoryCategory.PREFERENCE

    def test_relationship(self) -> None:
        assert categorize("My wife's name is Anjali.") is MemoryCategory.RELATIONSHIP

    def test_goal(self) -> None:
        assert categorize("I want to learn Rust this year.") is MemoryCategory.GOAL

    def test_project(self) -> None:
        assert categorize("I'm working on a new project called PARIKA.") is MemoryCategory.PROJECT

    def test_skill(self) -> None:
        assert categorize("I'm good at Python.") is MemoryCategory.SKILL

    def test_reminder_reference(self) -> None:
        assert categorize("Remind me to call the dentist.") is MemoryCategory.REMINDER_REFERENCE

    def test_falls_back_to_fact(self) -> None:
        assert categorize("The sky is blue.") is MemoryCategory.FACT
