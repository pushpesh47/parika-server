"""
Unit tests for `identity_guard.py` -- the deterministic Assistant
Identity Protection check `MemoryToolDriver` runs before ever calling
`MemoryManager.remember()` (PARIKA Memory Subsystem Refactor
Requirement A).
"""

from __future__ import annotations

from parika.tools.memory.identity_guard import (
    build_identity_terms,
    is_assistant_identity_content,
    is_identity_query,
)


class _FakeConfiguration:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


class TestBuildIdentityTerms:
    def test_extracts_configured_identity_names(self) -> None:
        configuration = _FakeConfiguration(
            {
                "assistant.name": "PARIKA",
                "assistant.full_name": "Personal Adaptive Responsive Intelligence Kernel Assistant",
                "assistant.nick_name": "PARI",
            }
        )

        terms = build_identity_terms(configuration)

        assert "parika" in terms
        assert "pari" in terms
        assert "personal adaptive responsive intelligence kernel assistant" in terms

    def test_none_configuration_returns_empty_set(self) -> None:
        assert build_identity_terms(None) == frozenset()

    def test_ignores_blank_values(self) -> None:
        configuration = _FakeConfiguration(
            {"assistant.name": "  ", "assistant.nick_name": ""}
        )

        assert build_identity_terms(configuration) == frozenset()


class TestIsAssistantIdentityContent:
    def _terms(self) -> frozenset[str]:
        return build_identity_terms(
            _FakeConfiguration(
                {
                    "assistant.name": "PARIKA",
                    "assistant.full_name": "Personal Adaptive Responsive Intelligence Kernel Assistant",
                    "assistant.nick_name": "PARI",
                }
            )
        )

    def test_flags_content_naming_the_assistant(self) -> None:
        assert is_assistant_identity_content(
            "PARIKA was created by Pushpesh Sharma from Independent.",
            self._terms(),
        )

    def test_flags_content_naming_the_nickname(self) -> None:
        assert is_assistant_identity_content(
            "My nickname (as the assistant) is PARI.", self._terms()
        )

    def test_flags_self_referential_creator_statement_without_configured_terms(
        self,
    ) -> None:
        # Even with no identity_terms at all (e.g. Configuration
        # unavailable), the self-referential patterns still apply.
        assert is_assistant_identity_content(
            "I was created by Pushpesh Sharma.", frozenset()
        )

    def test_flags_your_creator_phrasing(self) -> None:
        assert is_assistant_identity_content(
            "Your creator is Pushpesh Sharma.", frozenset()
        )

    def test_does_not_flag_an_ordinary_user_fact(self) -> None:
        assert not is_assistant_identity_content(
            "My name is Pushpesh Sharma.", self._terms()
        )

    def test_does_not_flag_unrelated_preference(self) -> None:
        assert not is_assistant_identity_content(
            "I like Python.", self._terms()
        )


class TestIsIdentityQuery:
    """
    PARIKA Memory & Session Retrieval Finalization, Bug #2: identity
    questions must never invoke any memory tool -- `chat_capability.
    gate_memory_authorization()` consults this to keep every memory
    tool out of the roster advertised for such a turn.
    """

    def test_flags_who_are_you(self) -> None:
        assert is_identity_query("Who are you?", frozenset())

    def test_flags_what_is_your_name(self) -> None:
        assert is_identity_query("What is your name?", frozenset())

    def test_flags_what_is_your_nickname(self) -> None:
        assert is_identity_query("What is your nickname?", frozenset())

    def test_flags_who_created_you(self) -> None:
        assert is_identity_query("Who created you?", frozenset())

    def test_flags_what_is_your_purpose(self) -> None:
        assert is_identity_query("What is your purpose?", frozenset())

    def test_flags_what_should_i_call_you(self) -> None:
        assert is_identity_query("What should I call you?", frozenset())

    def test_does_not_flag_ordinary_questions(self) -> None:
        assert not is_identity_query("What is the weather like?", frozenset())
        assert not is_identity_query("What do you remember about me?", frozenset())

    def test_does_not_flag_ordinary_statements(self) -> None:
        assert not is_identity_query("My name is Pushpesh.", frozenset())
