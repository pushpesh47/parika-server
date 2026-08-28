"""
Unit tests for `parika.interfaces.session_intent`: deterministic
detection of a request to search/recall previously saved sessions,
distinct from both the current conversation and permanent memory
(PARIKA Memory & Session Retrieval Finalization, Bugs #4/#5/#8).
"""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

from parika.interfaces.session_intent import (
    extract_session_search_topic,
    has_session_retrieval_intent,
)


class TestHasSessionRetrievalIntent:
    def test_recognizes_search_previous_sessions_for_topic(self) -> None:
        assert has_session_retrieval_intent("Search previous sessions for Docker.")

    def test_recognizes_search_all_previous_chats(self) -> None:
        assert has_session_retrieval_intent("Search all previous chats for Docker.")

    def test_recognizes_search_previous_sessions_and_introduce_me(self) -> None:
        assert has_session_retrieval_intent(
            "Search previous sessions and introduce me."
        )

    def test_recognizes_what_did_we_discuss_last_week(self) -> None:
        assert has_session_retrieval_intent("What did we discuss last week?")

    def test_recognizes_tell_me_what_we_discussed_last_week(self) -> None:
        assert has_session_retrieval_intent("Tell me what we discussed last week.")

    def test_recognizes_find_where_i_mentioned(self) -> None:
        assert has_session_retrieval_intent("Find where I mentioned Laravel.")

    def test_recognizes_summarize_our_previous_discussions(self) -> None:
        assert has_session_retrieval_intent("Summarize our previous discussions.")

    def test_does_not_flag_ordinary_questions(self) -> None:
        for text in (
            "What's the weather like today?",
            "What is the capital of France?",
            "Convert 100 USD to EUR.",
        ):
            assert not has_session_retrieval_intent(text), text

    def test_does_not_flag_permanent_memory_questions(self) -> None:
        assert not has_session_retrieval_intent(
            "Tell me what you remember about me."
        )

    def test_does_not_flag_current_conversation_questions(self) -> None:
        """
        A question about the *current* conversation is already
        answered from the rolling message history, with no retrieval
        needed at all -- must never be confused with Session
        Retrieval (Bug #5).
        """

        assert not has_session_retrieval_intent(
            "Earlier in this conversation what did I say?"
        )


class TestExtractSessionSearchTopic:
    def test_extracts_docker(self) -> None:
        assert (
            extract_session_search_topic("Search previous sessions for Docker.")
            == "Docker"
        )

    def test_extracts_laravel(self) -> None:
        assert (
            extract_session_search_topic("Find where I mentioned Laravel.")
            == "Laravel"
        )

    def test_returns_none_when_no_topic_keyword_remains(self) -> None:
        assert (
            extract_session_search_topic("Summarize our previous discussions.")
            is None
        )
        assert (
            extract_session_search_topic(
                "Search previous sessions and introduce me."
            )
            is None
        )
