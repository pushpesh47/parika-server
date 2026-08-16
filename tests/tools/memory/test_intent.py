"""
Unit tests for `parika.tools.memory.intent`: deterministic detection
of an explicit memory-write request (PARIKA Memory & Session
Retrieval Finalization, Bug #1).
"""

from __future__ import annotations

from parika.tools.memory.intent import has_explicit_memory_intent


class TestHasExplicitMemoryIntent:
    def test_recognizes_remember_this(self) -> None:
        assert has_explicit_memory_intent("Remember this.")

    def test_recognizes_remember_that(self) -> None:
        assert has_explicit_memory_intent("Remember that I like tea.")

    def test_recognizes_remember_my_name_is(self) -> None:
        assert has_explicit_memory_intent("Remember my name is Pushpesh.")

    def test_recognizes_store_this(self) -> None:
        assert has_explicit_memory_intent("Store this.")

    def test_recognizes_save_this(self) -> None:
        assert has_explicit_memory_intent("Save this.")

    def test_recognizes_note_this(self) -> None:
        assert has_explicit_memory_intent("Note this: I use Laravel.")

    def test_recognizes_dont_forget(self) -> None:
        assert has_explicit_memory_intent("Don't forget this.")
        assert has_explicit_memory_intent("Dont forget I have a meeting.")

    def test_recognizes_add_this_to_memory(self) -> None:
        assert has_explicit_memory_intent("Add this to memory.")

    def test_recognizes_keep_this_in_mind(self) -> None:
        assert has_explicit_memory_intent("Keep this in mind.")

    def test_recognizes_please_remember(self) -> None:
        assert has_explicit_memory_intent("Please remember my birthday is in May.")

    def test_does_not_flag_ordinary_statements(self) -> None:
        for text in (
            "My name is Pushpesh.",
            "I like Python.",
            "My daughter is Kavya.",
            "I use Laravel.",
            "I live in India.",
        ):
            assert not has_explicit_memory_intent(text), text

    def test_does_not_flag_a_question_about_remembering(self) -> None:
        """
        An interrogative use of "remember" is not an instruction to
        store anything -- deliberately not recognized, per the
        module's documented precision-over-recall trade-off.
        """

        assert not has_explicit_memory_intent("Do you remember what I told you?")

    def test_does_not_flag_a_statement_that_the_user_remembers_something(
        self,
    ) -> None:
        assert not has_explicit_memory_intent("I remember you mentioned Docker.")
