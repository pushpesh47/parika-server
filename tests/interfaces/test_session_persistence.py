"""
Unit tests for InterfaceSession's session-persistence extension:
`session_store`, `save()`, `load()`, and `list_sessions()`.

Exercised against a real ParikaRuntime (matching test_session.py's
pattern), with only the outermost Ollama HTTP transport faked.
"""


from __future__ import annotations
from tests.conftest_db import build_test_db_config

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.interfaces.session import InterfaceSession
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore, SessionNotFoundError
from parika.core.database.pool import PoolManager
from parika.core.database.config import DatabaseConfig


# Test database configuration
# Test database configuration from environment
# TEST_DATABASE_CONFIG = { ... }  # Replaced by build_test_db_config()


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = build_test_db_config()
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


class _ScriptedOllamaTransport:
    """
    Deterministic OllamaTransport: canned model discovery + health,
    and a FIFO queue of `/api/chat` responses.
    """

    def __init__(self) -> None:
        self._chat_queue: list[dict[str, Any]] = []
        self.chat_payloads: list[dict[str, Any]] = []
        self._decomposition_call_count = 0

    def queue_chat_response(self, response: dict[str, Any]) -> None:
        self._chat_queue.append(response)

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        if url.endswith("/api/tags"):
            return {"models": [{"name": "test-model"}]}

        if url.endswith("/api/show"):
            return {"capabilities": ["completion", "tools"]}

        if url.endswith("/api/version"):
            return {"version": "0.0.0-test"}

        if url.endswith("/api/chat"):
            self.chat_payloads.append(dict(payload or {}))
            
            # Check if this is a decomposition request (contains "Goal Decomposer" in system prompt)
            if payload and "messages" in payload:
                for msg in payload["messages"]:
                    if msg.get("role") == "system" and "Goal Decomposer" in msg.get("content", ""):
                        self._decomposition_call_count += 1
                        # Return a valid decomposition JSON for simple requests
                        # Use the next queued response's content as the message for chat.respond
                        # BUT DO NOT CONSUME THE QUEUE - decomposition calls are internal
                        if self._chat_queue:
                            next_response = self._chat_queue[0]  # Peek, don't pop
                            message_content = next_response.get("message", {}).get("content", "Hi there.")
                        else:
                            message_content = "Hi there."
                        return {
                            "message": {
                                "role": "assistant",
                                "content": f'{{"goals": [{{"id": "goal_0", "capability_id": "chat.respond", "inputs": {{"message": "{message_content}"}}, "depends_on": []}}]}}',
                                "done": True
                            },
                            "done": True
                        }
            
            # Only consume queue for non-decomposition calls
            return self._chat_queue.pop(0)

        return {}

    def stream_lines(
        self, method: str, url: str, *, payload, timeout
    ) -> Iterator[dict[str, Any]]:
        return iter(())


@pytest.fixture
def transport() -> _ScriptedOllamaTransport:
    return _ScriptedOllamaTransport()


@pytest.fixture
def runtime(transport: _ScriptedOllamaTransport, tmp_path, _test_db_pool):
    runtime = build_default_runtime(
        ollama_transport=transport, data_directory=tmp_path / "data", sync_pool=_test_db_pool
    )
    yield runtime
    shutdown_runtime(runtime)


@pytest.fixture
def session_store(_test_db_pool) -> Iterator[PostgreSQLSessionStore]:
    store = PostgreSQLSessionStore(_test_db_pool)
    store.initialize()
    # Clean up before each test
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM core.session_message;")
            cur.execute("DELETE FROM core.session;")
            conn.commit()

    yield store

    store.shutdown()


@pytest.fixture(autouse=True)
def _clear_memory_db(_test_db_pool):
    """Clear the memory database before each test to ensure isolation."""
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM core.memory;")
            conn.commit()
    yield


def _simple_answer(text: str) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": text}, "done": True}


class TestSessionStorePersistence:
    def test_none_store_is_fully_backward_compatible(self, runtime) -> None:
        session = InterfaceSession(runtime, system_prompt=None)

        assert session.session_store is None
        # save() is a no-op without a store -- must not raise.
        session.save()

    def test_construction_ensures_session_row(
        self, runtime, session_store: PostgreSQLSessionStore
    ) -> None:
        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )

        assert session_store.get_session(session.id) is not None

    def test_submit_text_persists_user_and_assistant_turns(
        self, runtime, transport: _ScriptedOllamaTransport, session_store: PostgreSQLSessionStore
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hi there."))

        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        session.submit_text("hello")

        messages = session_store.get_messages(session.id)

        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content == "hello"
        assert messages[1].content == "Hi there."


class TestSave:
    def test_derives_title_from_first_user_message(
        self, runtime, transport: _ScriptedOllamaTransport, session_store: PostgreSQLSessionStore
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hi there."))

        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        session.submit_text("What is the weather like today?")
        session.save()

        summary = session_store.get_session(session.id)
        assert summary is not None
        assert summary.title == "What is the weather like today?"

    def test_does_not_overwrite_existing_title(
        self, runtime, transport: _ScriptedOllamaTransport, session_store: PostgreSQLSessionStore
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hi there."))

        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        session.submit_text("hello")
        session_store.set_title(session.id, "Custom Title")

        session.save()

        summary = session_store.get_session(session.id)
        assert summary is not None
        assert summary.title == "Custom Title"

    def test_does_not_record_implicit_preferences_as_memory(
        self, runtime, transport: _ScriptedOllamaTransport, session_store: PostgreSQLSessionStore
    ) -> None:
        """
        Ordinary conversational statements -- even ones that state a
        preference (e.g. "I prefer concise answers") -- must never be
        auto-recorded as a permanent memory: PARIKA Memory Subsystem
        Refactor's "Strictly Explicit Memory" requirement means memory
        is only ever created through the `memory.remember` Capability,
        never as a side effect of `save()`. See `session.py`'s
        `save()` docstring for why the previous auto-recording
        behavior was removed.
        """

        transport.queue_chat_response(_simple_answer("Noted."))

        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        session.submit_text("I prefer concise answers.")
        session.save()

        assert runtime.memory_manager.count() == 0

    def test_save_is_idempotent_and_creates_no_memory(
        self, runtime, transport: _ScriptedOllamaTransport, session_store: PostgreSQLSessionStore
    ) -> None:
        transport.queue_chat_response(_simple_answer("Noted."))

        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        session.submit_text("I prefer concise answers.")
        session.save()
        session.save()

        assert runtime.memory_manager.count() == 0


class TestLoad:
    def test_raises_when_session_missing(self, runtime, session_store: PostgreSQLSessionStore) -> None:
        with pytest.raises(SessionNotFoundError):
            InterfaceSession.load("missing", runtime, session_store)

    def test_restores_conversation_history(
        self, runtime, transport: _ScriptedOllamaTransport, session_store: PostgreSQLSessionStore
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hi there."))

        original = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        original.submit_text("hello")

        restored = InterfaceSession.load(original.id, runtime, session_store)

        assert [e.text for e in restored.history()] == ["hello", "Hi there."]

    def test_restored_messages_are_fed_back_to_the_model(
        self, runtime, transport: _ScriptedOllamaTransport, session_store: PostgreSQLSessionStore
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hi there."))

        original = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        original.submit_text("hello")

        restored = InterfaceSession.load(original.id, runtime, session_store)

        # The restored session's rolling _messages should include the
        # prior turns (used internally by submit_text()).
        contents = [m.content for m in restored._messages]
        assert "hello" in contents
        assert "Hi there." in contents


class TestSessionRetrieval:
    """
    PARIKA Memory & Session Retrieval Finalization, Bugs #4/#5/#6/#7/
    #8: previously saved sessions must be reachable from natural
    language, without ever polluting permanent memory or the current
    conversation, and without scanning every saved session on every
    ordinary turn.
    """

    def test_explicit_session_search_injects_a_matching_excerpt(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
        session_store: PostgreSQLSessionStore,
    ) -> None:
        # Queue responses for both sessions' actual chat calls
        # (decomposition calls use synthetic responses and don't consume the queue)
        transport.queue_chat_response(_simple_answer("Noted."))
        transport.queue_chat_response(
            _simple_answer("You previously mentioned Docker.")
        )
    
        earlier = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        earlier.submit_text("Docker is great for containerizing apps.")
    
        current = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        current.submit_text("Search previous sessions for Docker.")
    
        # With multi-goal decomposition, the actual chat calls are at indices 1 and 3
        # (0=first decomposition, 1=first actual, 2=second decomposition, 3=second actual)
        sent_messages = transport.chat_payloads[3]["messages"]
        system_contents = [m["content"] for m in sent_messages if m["role"] == "system"]
    
        assert any("Docker" in content for content in system_contents)
        assert any(
            "previously saved sessions" in content for content in system_contents
        )

    def test_session_search_never_creates_permanent_memory(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
        session_store: PostgreSQLSessionStore,
    ) -> None:
        transport.queue_chat_response(_simple_answer("Noted."))
        transport.queue_chat_response(_simple_answer("Here you go."))

        earlier = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        earlier.submit_text("Docker is great for containerizing apps.")

        current = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        current.submit_text("Search previous sessions for Docker.")

        assert runtime.memory_manager.count() == 0

    def test_session_search_excludes_the_current_sessions_own_message(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
        session_store: PostgreSQLSessionStore,
    ) -> None:
        """
        The current turn's own user message is already persisted to
        the store before Session Retrieval runs -- it must never be
        echoed back to the model as if it were a "previous session"
        match.
        """

        transport.queue_chat_response(_simple_answer("Sure."))

        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        session.submit_text("Search previous sessions for Docker.")

        # With multi-goal decomposition, the actual chat call is at index 1
        # (0=decomposition, 1=actual chat)
        sent_messages = transport.chat_payloads[1]["messages"]
        system_contents = [m["content"] for m in sent_messages if m["role"] == "system"]

        # No earlier session ever mentioned Docker, so either no
        # session-retrieval system message is present, or it reports
        # no match -- but it must never quote back this exact turn's
        # own request as a "previous session" excerpt.
        assert not any(
            "Search previous sessions for Docker" in content
            for content in system_contents
        )

    def test_ordinary_message_does_not_trigger_session_retrieval(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
        session_store: PostgreSQLSessionStore,
    ) -> None:
        """
        Bug #8 (performance): normal questions must not trigger
        Session Retrieval at all.
        """

        transport.queue_chat_response(_simple_answer("Hello!"))

        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        session.submit_text("Hello there.")

        sent_messages = transport.chat_payloads[0]["messages"]
        system_contents = [m["content"] for m in sent_messages if m["role"] == "system"]

        assert not any(
            "previously saved sessions" in content for content in system_contents
        )

    def test_current_conversation_question_does_not_trigger_session_retrieval(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
        session_store: PostgreSQLSessionStore,
    ) -> None:
        """Bug #5: a question about *this* conversation is not a session-search request."""

        transport.queue_chat_response(_simple_answer("First."))
        transport.queue_chat_response(_simple_answer("You said hello."))

        session = InterfaceSession(
            runtime, system_prompt=None, session_store=session_store
        )
        session.submit_text("Hello there.")
        session.submit_text("Earlier in this conversation what did I say?")

        sent_messages = transport.chat_payloads[1]["messages"]
        system_contents = [m["content"] for m in sent_messages if m["role"] == "system"]

        assert not any(
            "previously saved sessions" in content for content in system_contents
        )

    def test_session_search_without_a_store_is_a_no_op(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """A session-less (purely in-memory) InterfaceSession must never fail or hang."""

        transport.queue_chat_response(_simple_answer("Sure."))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text("Search previous sessions for Docker.")

        assert result.succeeded


class TestListSessions:
    def test_lists_every_saved_session(
        self, runtime, session_store: PostgreSQLSessionStore
    ) -> None:
        InterfaceSession(runtime, system_prompt=None, session_store=session_store)
        InterfaceSession(runtime, system_prompt=None, session_store=session_store)

        summaries = InterfaceSession.list_sessions(session_store)

        assert len(summaries) == 2
