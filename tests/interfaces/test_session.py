"""
Unit tests for `parika.interfaces.session.InterfaceSession`.

Exercised against a real `ParikaRuntime` (real Brain, Planner,
CapabilityExecutor, ProviderManager, and Ollama provider driver) with
only the outermost Ollama HTTP transport faked, so the full
request-construction -> Brain -> Planner -> Provider round trip is
verified end to end.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from parika.core.provider_manager.chat_result import ChatResult
from parika.interfaces.history import HistoryRole
from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.interfaces.session import InterfaceSession
from parika.providers.ollama.responses import OllamaChatResponse
from parika.core.database.pool import PoolManager
from parika.core.database.config import DatabaseConfig


# Test database configuration
TEST_DATABASE_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 5432,
    "database": "parika_test",
    "username": "postgres",
    "password": "dba",
    "pool_min_size": 2,
    "pool_max_size": 10,
    "connect_timeout": 10.0,
    "statement_timeout": 0.0,
    "application_name": "parika_test",
}


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = DatabaseConfig(**TEST_DATABASE_CONFIG)
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
                        if self._chat_queue:
                            next_response = self._chat_queue[0]
                            message_content = next_response.get("message", {}).get("content", "Hi there.")
                            return {
                                "message": {
                                    "role": "assistant",
                                    "content": f'{{"goals": [{{"id": "goal_0", "capability_id": "chat.respond", "inputs": {{"message": "{message_content}"}}, "depends_on": []}}]}}',
                                    "done": True
                                },
                                "done": True
                            }
                        else:
                            return {
                                "message": {
                                    "role": "assistant",
                                    "content": '{"goals": [{"id": "goal_0", "capability_id": "chat.respond", "inputs": {"message": "Hi there."}, "depends_on": []}]}',
                                    "done": True
                                },
                                "done": True
                            }
            
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
    # Isolated, disposable data directory so Memory/Knowledge/
    # Experience state never accumulates in the real project's data/
    # directory across test runs.
    # ComfyUI model discovery is disabled here for the same
    # determinism reason: this fixture's session/conversation-mechanics
    # tests assert exact message role sequences (e.g. "no system message
    # injected"), which must not vary depending on whether a ComfyUI
    # server happens to be reachable in the environment running the
    # tests (see the Worker Model Inventory feature in
    # `ai_context/goal_builder.py`, which only activates once more
    # than one Provider model is registered).
    runtime = build_default_runtime(
        ollama_transport=transport,
        discover_comfyui_models=False,
        data_directory=tmp_path / "data",
        sync_pool=_test_db_pool,
    )
    yield runtime
    shutdown_runtime(runtime)


def _simple_answer(text: str) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": text}, "done": True}


class TestSubmitTextSuccess:
    def test_returns_answer_and_records_history(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hi there."))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text("hello")

        assert result.succeeded
        assert result.chat_response is not None
        assert result.chat_response.message.content == "Hi there."

        # Provider independence: InterfaceSession exposes the
        # provider-independent `ChatResult`, never the Ollama
        # provider's own concrete `OllamaChatResponse`, even though
        # Ollama is the Provider that actually executed this turn.
        assert isinstance(result.chat_response, ChatResult)
        assert not isinstance(result.chat_response, OllamaChatResponse)

        history = session.history()
        assert [entry.role for entry in history] == [
            HistoryRole.USER,
            HistoryRole.ASSISTANT,
        ]
        assert history[0].text == "hello"
        assert history[1].text == "Hi there."

    def test_conversation_history_grows_across_turns(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
    ) -> None:
        transport.queue_chat_response(_simple_answer("First reply."))
        transport.queue_chat_response(_simple_answer("Second reply."))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("first message")
        session.submit_text("second message")

        # With decomposition, each submit_text makes 2 calls:
        # [0]=decomp1, [1]=exec1, [2]=decomp2, [3]=exec2
        second_execution_payload = transport.chat_payloads[3]
        roles = [message["role"] for message in second_execution_payload["messages"]]

        # user, assistant, system (worker inventory), user (this turn's message).
        assert roles == ["user", "assistant", "system", "user"]

    def test_tool_calling_round_trip_appends_exactly_one_assistant_entry(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
    ) -> None:
        """
        Regression test for duplicate-assistant-response prevention:
        a turn that involves a tool round trip must still append
        exactly one ASSISTANT history entry (the final, tool-call-free
        answer) - never the intermediate tool-calling message, and
        never twice.
        """

        transport.queue_chat_response(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "get_current_datetime",
                                "arguments": {},
                            }
                        }
                    ],
                },
                "done": True,
            }
        )
        transport.queue_chat_response(
            _simple_answer("It is currently noon UTC.")
        )

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text("what time is it?")

        assert result.succeeded
        assert result.chat_response is not None
        assert result.chat_response.message.content == (
            "It is currently noon UTC."
        )
        assert len(result.chat_response.tool_invocations) == 1

        history = session.history()
        assert [entry.role for entry in history] == [
            HistoryRole.USER,
            HistoryRole.ASSISTANT,
        ]
        assert history[1].text == "It is currently noon UTC."

    def test_system_prompt_is_seeded_as_first_message(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
    ) -> None:
        transport.queue_chat_response(_simple_answer("ok"))

        session = InterfaceSession(runtime, system_prompt="Be helpful.")
        session.submit_text("hello")

        # With decomposition, first payload is decomposition, second is execution
        first_execution_payload = transport.chat_payloads[1]
        assert first_execution_payload["messages"][0]["role"] == "system"
        assert first_execution_payload["messages"][0]["content"] == "Be helpful."


class TestExecutionProgressTrail:
    """
    Phase 3.5b: `LastTurnDiagnostics.progress_trail` captures every
    `ProgressEvent` published during `submit_text()`, and does not
    interfere with a live subscriber observing the same events.
    """

    def test_progress_trail_includes_brain_execution_tree(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hi there."))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("hello")

        diagnostics = session.last_turn_diagnostics
        assert diagnostics is not None

        source_ids = [event.source_id for event in diagnostics.progress_trail]
        assert "brain.execution" in source_ids
        assert "brain.planning" in source_ids

    def test_live_subscriber_still_observes_events_independently(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
    ) -> None:
        """
        Collecting into progress_trail must not prevent (or duplicate
        for) any other subscriber already watching the EventBus, e.g.
        a Console -- the two must be fully independent.
        """

        transport.queue_chat_response(_simple_answer("Hi there."))

        live_events: list[object] = []
        runtime.event_bus.subscribe("progress.started", live_events.append)

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("hello")

        assert len(live_events) >= 1

        # The temporary internal subscription must have been removed
        # after the turn completes -- a second turn must not double
        # the trail from a leaked subscriber.
        transport.queue_chat_response(_simple_answer("Second."))
        session.submit_text("hello again")

        diagnostics = session.last_turn_diagnostics
        assert diagnostics is not None
        assert diagnostics.progress_trail.count(
            diagnostics.progress_trail[0]
        ) == 1


class TestSubmitTextFailure:
    def test_planning_failure_is_reported_without_raising(
        self,
        transport: _ScriptedOllamaTransport,
        tmp_path,
        _test_db_pool,
    ) -> None:
        # No models discovered -> Planner cannot satisfy the LLM
        # capability -> planning failure, not an exception.
        runtime = build_default_runtime(
            ollama_transport=transport,
            discover_ollama_models=False,
            discover_comfyui_models=False,
            data_directory=tmp_path / "data",
            sync_pool=_test_db_pool,
        )

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text("hello")

        assert not result.succeeded
        assert result.chat_response is None
        assert result.error_message is not None

        history = session.history()
        assert history[-1].role is HistoryRole.ERROR

        shutdown_runtime(runtime)


class TestClear:
    def test_clear_preserves_system_prompt_but_drops_conversation(
        self,
        runtime,
        transport: _ScriptedOllamaTransport,
    ) -> None:
        transport.queue_chat_response(_simple_answer("first"))
        transport.queue_chat_response(_simple_answer("second"))
    
        session = InterfaceSession(runtime, system_prompt="Be helpful.")
        session.submit_text("hello")
    
        session.clear()
        assert session.history() == ()
    
        session.submit_text("hello again")
    
        second_payload = transport.chat_payloads[1]
        roles = [message["role"] for message in second_payload["messages"]]
        # Two system messages: system prompt + worker inventory
        assert roles == ["system", "system", "user"]


class TestRecord:
    def test_record_appends_history_entry(self, runtime) -> None:
        session = InterfaceSession(runtime, system_prompt=None)

        session.record(HistoryRole.COMMAND, "/status")

        assert session.history() == (
            session.history()[0],
        )
        assert session.history()[0].role is HistoryRole.COMMAND
        assert session.history()[0].text == "/status"
