"""
End-to-end integration tests proving Context Assembly runs
automatically for every chat turn, before Planner, integrating
permanent Memory into the actual HTTP request sent to the model --
Phase 1 Completion Specification sections 1, 3, 4, 20, 21.

Uses a real `ParikaRuntime` (real Brain, Planner, MemoryManager,
CapabilityExecutor, Ollama provider driver) with only the outermost
Ollama HTTP transport faked, so the full request-construction ->
Context Assembly -> Brain -> Planner -> Provider round trip is
verified end to end, and the captured `/api/chat` payload is inspected
directly.
"""

from __future__ import annotations

from typing import Any

import pytest

from parika.core.memory_manager.memory_category import MemoryCategory
from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.interfaces.session import InterfaceSession


class _ScriptedOllamaTransport:
    def __init__(self) -> None:
        self._chat_queue: list[dict[str, Any]] = []
        self.chat_payloads: list[dict[str, Any]] = []

    def queue_chat_response(self, response: dict[str, Any]) -> None:
        self._chat_queue.append(response)

    def request_json(self, method, url, *, payload, timeout) -> dict[str, Any]:
        if url.endswith("/api/tags"):
            return {"models": [{"name": "test-model"}]}
        if url.endswith("/api/show"):
            return {"capabilities": ["completion", "tools"]}
        if url.endswith("/api/version"):
            return {"version": "0.0.0-test"}
        if url.endswith("/api/chat"):
            self.chat_payloads.append(dict(payload or {}))
            return self._chat_queue.pop(0)
        return {}

    def stream_lines(self, method, url, *, payload, timeout):
        return iter(())


@pytest.fixture
def transport() -> _ScriptedOllamaTransport:
    return _ScriptedOllamaTransport()


@ pytest.fixture
def runtime(transport: _ScriptedOllamaTransport, tmp_path):
    # Isolated, disposable data directory: without this, MemoryManager
    # would persist into the real project's data/ (by
    # design -- that IS "true permanent memory" in production), which
    # would make absolute count()/get_all() assertions here depend on
    # every other test run's accumulated state.
    # ComfyUI model discovery is disabled here for the same
    # determinism reason: this fixture's context-assembly assertions
    # check exact message role sequences (e.g. "no system message
    # injected"), which must not vary depending on whether a ComfyUI
    # server happens to be reachable in the environment running the
    # tests (see the Worker Model Inventory feature in
    # `ai_context/goal_builder.py`, which only activates once more
    # than one Provider model is registered).
    runtime = build_default_runtime(
        ollama_transport=transport,
        discover_comfyui_models=False,
        data_directory=tmp_path / "data",
    )
    yield runtime
    shutdown_runtime(runtime)


def _simple_answer(text: str) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": text}, "done": True}


class TestContextAssemblyAutomaticMemoryRetrieval:
    def test_remembered_fact_is_retrieved_and_injected_into_the_next_request(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        Conversation A remembers a fact; Conversation B (a brand new
        InterfaceSession, sharing only the runtime's MemoryManager) asks
        about it -- the fact must appear in the actual HTTP request
        payload sent to the model, without loading Conversation A's
        history, proving Memory is retrieved automatically and is
        independent of conversation history (section 1's acceptance
        example).
        """

        runtime.memory_manager.remember(content="The user's name is Pushpesh.")

        transport.queue_chat_response(_simple_answer("Your name is Pushpesh."))

        conversation_b = InterfaceSession(runtime, system_prompt=None)
        conversation_b.submit_text("What is my name?")

        assert len(transport.chat_payloads) == 1
        sent_messages = transport.chat_payloads[0]["messages"]
        system_contents = [m["content"] for m in sent_messages if m["role"] == "system"]

        assert any("Pushpesh" in content for content in system_contents)

    def test_context_message_is_not_permanently_added_to_history(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        The injected context message must not accumulate in
        `InterfaceSession._messages` turn after turn -- Context
        Assembly re-runs fresh every turn.
        """

        runtime.memory_manager.remember(content="The user's name is Pushpesh.")

        transport.queue_chat_response(_simple_answer("Your name is Pushpesh."))
        transport.queue_chat_response(_simple_answer("Nice to meet you."))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("What is my name?")
        session.submit_text("Hello again.")

        assert not any(
            "Pushpesh" in m.content for m in session._messages if m.role == "user"
        )
        # The rolling history only ever grows by exactly 2 messages per turn
        # (user + assistant), never by the injected context message too.
        assert len(session._messages) == 4

    def test_no_context_injected_when_nothing_relevant_is_remembered(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hello!"))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("Hello there.")

        sent_messages = transport.chat_payloads[0]["messages"]
        assert not any(m["role"] == "system" for m in sent_messages)

    def test_knowledge_is_retrieved_and_injected_into_the_request(
        self, runtime, transport: _ScriptedOllamaTransport, tmp_path
    ) -> None:
        """
        Section 13 ("Knowledge retrieval happens during Context
        Assembly. Never after Provider execution."), verified through
        the full live pipeline exactly like Memory above.
        """

        from uuid import uuid4

        from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
        from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
        from parika.core.knowledge_manager.knowledge_source import KnowledgeSource

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "guide.md").write_text(
            "# Refunds\n\nOur refund policy allows returns within 30 days.\n",
            encoding="utf-8",
        )

        source = KnowledgeSource(
            id=uuid4(),
            name="policy-docs",
            kind=KnowledgeSourceKind.DOCUMENTATION,
            location=str(docs_dir),
            status=KnowledgeSourceStatus.AVAILABLE,
        )
        runtime.knowledge_manager.register_source(source)
        runtime.knowledge_manager.index(source.id)

        transport.queue_chat_response(
            _simple_answer("Refunds are allowed within 30 days.")
        )

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("What is the refund policy?")

        sent_messages = transport.chat_payloads[0]["messages"]
        system_contents = [m["content"] for m in sent_messages if m["role"] == "system"]

        assert any("30 days" in content for content in system_contents)

    def test_memory_shared_across_independent_sessions(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        Section 1's core acceptance criterion: a permanent memory
        registered independently of any session is retrievable by a
        brand new session that never loaded the original conversation.
        """

        runtime.memory_manager.remember(
            content="The user prefers concise answers.",
            category=MemoryCategory.PREFERENCE,
        )

        transport.queue_chat_response(_simple_answer("Understood, I'll be concise."))

        fresh_session = InterfaceSession(runtime, system_prompt=None)
        # Shares the literal token "concise" with the stored memory --
        # Memory retrieval is deterministic/lexical (BM25), not
        # semantic (see Core_Component_Responsibilities.md), so an
        # assertion here must share an exact word, not merely a
        # paraphrase, with the stored content.
        fresh_session.submit_text("Should your answers be concise?")

        sent_messages = transport.chat_payloads[0]["messages"]
        system_contents = [m["content"] for m in sent_messages if m["role"] == "system"]

        assert any("concise" in content for content in system_contents)


class TestPermanentMemorySurvivesRestart:
    """
    Phase 1 Completion Specification section 1 / 23: "Permanent memory
    survives restart" -- verified by fully shutting down one runtime
    and building a brand new one against the same on-disk data
    directory (simulating an application restart), rather than reusing
    the same in-process MemoryManager instance.
    """

    def test_memory_survives_a_full_runtime_restart(
        self, tmp_path
    ) -> None:
        data_directory = tmp_path / "data"

        first_transport = _ScriptedOllamaTransport()
        first_runtime = build_default_runtime(
            ollama_transport=first_transport, data_directory=data_directory
        )
        try:
            first_runtime.memory_manager.remember(
                content="The user's name is Pushpesh."
            )
        finally:
            shutdown_runtime(first_runtime)

        second_transport = _ScriptedOllamaTransport()
        second_runtime = build_default_runtime(
            ollama_transport=second_transport, data_directory=data_directory
        )
        try:
            assert second_runtime.memory_manager.count() == 1
            restored = second_runtime.memory_manager.get_all()[0]
            assert "Pushpesh" in restored.content
        finally:
            shutdown_runtime(second_runtime)


class TestSessionRemainsIsolated:
    """
    Phase 1 Completion Specification section 23: "Session remains
    isolated" -- unlike permanent Memory (shared across every
    conversation by design), each session's own conversation history
    must never leak into a different session.
    """

    def test_conversation_history_does_not_leak_between_sessions(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        transport.queue_chat_response(_simple_answer("Sure, noted."))
        transport.queue_chat_response(_simple_answer("I don't have that information."))

        session_a = InterfaceSession(runtime, system_prompt=None)
        session_a.submit_text("My favorite color is teal, just for this chat.")

        session_b = InterfaceSession(runtime, system_prompt=None)
        session_b.submit_text("What did I just tell you?")

        # session_b's own request must never contain session_a's
        # conversation turns -- only whatever permanent Memory (none
        # was created here) or Knowledge Context Assembly retrieves.
        sent_messages = transport.chat_payloads[1]["messages"]
        contents = [m["content"] for m in sent_messages]

        assert not any("teal" in content for content in contents)
        assert session_a.id != session_b.id
        assert len(session_a._messages) != 0
        assert all(m.role != "user" or "teal" not in m.content for m in session_b._messages[:-1])


class TestMemoryToolTruthfulResponses:
    def test_model_calling_memory_remember_actually_persists_it(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        Phase 1 Completion Specification sections 1, 11 ("truthful
        memory responses"): the model's claim to have remembered
        something is only ever truthful because it is generated after
        the native tool-calling round trip actually persisted the
        memory through MemoryManager -- never a hardcoded response.
        """

        transport.queue_chat_response(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "memory_remember",
                                "arguments": {"content": "The user's name is Pushpesh."},
                            }
                        }
                    ],
                },
                "done": True,
            }
        )
        transport.queue_chat_response(
            _simple_answer("Got it, I'll remember that your name is Pushpesh.")
        )

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text("Remember that my name is Pushpesh.")

        assert result.succeeded
        assert runtime.memory_manager.count() == 1
        stored = runtime.memory_manager.get_all()[0]
        assert "Pushpesh" in stored.content

    def test_memory_search_and_forget_are_always_advertised(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hello!"))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("Hello there.")

        advertised_tools = transport.chat_payloads[0].get("tools", [])
        tool_names = {tool["function"]["name"] for tool in advertised_tools}

        assert "memory_search" in tool_names
        assert "memory_forget" in tool_names

    def test_memory_remember_is_not_advertised_without_explicit_intent(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        PARIKA Memory & Session Retrieval Finalization, Bug #1:
        `memory_remember` must never be advertised -- and therefore
        never callable -- for an ordinary message, regardless of
        provider/model behavior.
        """

        transport.queue_chat_response(_simple_answer("Hello!"))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("Hello there.")

        advertised_tools = transport.chat_payloads[0].get("tools", [])
        tool_names = {tool["function"]["name"] for tool in advertised_tools}

        assert "memory_remember" not in tool_names

    def test_memory_remember_is_advertised_for_explicit_request(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        transport.queue_chat_response(_simple_answer("Sure."))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("Remember that my name is Pushpesh.")

        advertised_tools = transport.chat_payloads[0].get("tools", [])
        tool_names = {tool["function"]["name"] for tool in advertised_tools}

        assert "memory_remember" in tool_names

    def test_ordinary_statement_never_creates_a_memory_end_to_end(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        Even if the model somehow still attempted to call
        `memory_remember` for an ordinary statement, it is not
        advertised, so `ToolCallResolver` would reject it as an
        unknown tool before Brain/MemoryManager is ever reached; here
        we simply verify the end-to-end outcome: no memory is created
        for an ordinary statement that never asked to be remembered.
        """

        transport.queue_chat_response(_simple_answer("Nice to meet you."))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("My name is Pushpesh.")

        assert runtime.memory_manager.count() == 0

    def test_hallucinated_memory_remember_call_is_rejected_without_persisting(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        Deterministic authorization (Bug #1) must hold even if a
        model ignores the advertised tool roster and emits a
        `memory_remember` tool call anyway for an ordinary message
        that never asked to be remembered: since the tool was never
        advertised for this turn, `ToolCallResolver` rejects it as an
        unknown tool before Brain/Planner/MemoryManager is ever
        reached -- no memory is created, regardless of model
        behavior.
        """

        transport.queue_chat_response(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "memory_remember",
                                "arguments": {"content": "The user's name is Pushpesh."},
                            }
                        }
                    ],
                },
                "done": True,
            }
        )
        transport.queue_chat_response(_simple_answer("Nice to meet you, Pushpesh."))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text("My name is Pushpesh.")

        assert result.succeeded
        assert runtime.memory_manager.count() == 0

        # The tool-result message fed back to the model must report
        # the tool as unknown, never a fabricated success.
        second_payload = transport.chat_payloads[1]
        tool_messages = [m for m in second_payload["messages"] if m["role"] == "tool"]
        assert len(tool_messages) == 1
        assert "Unknown tool" in tool_messages[0]["content"]

    def test_duplicate_explicit_remember_requests_create_only_one_memory(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        for _ in range(2):
            transport.queue_chat_response(
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "memory_remember",
                                    "arguments": {
                                        "content": "The user's name is Pushpesh."
                                    },
                                }
                            }
                        ],
                    },
                    "done": True,
                }
            )
            transport.queue_chat_response(
                _simple_answer("Got it, I'll remember that your name is Pushpesh.")
            )

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("Remember my name is Pushpesh.")
        session.submit_text("Remember my name is Pushpesh.")

        assert runtime.memory_manager.count() == 1


class TestToolAdvertisementFiltering:
    """
    AI Context Engineering (see `docs/architecture/
    Request_Understanding.md`): Automatic Capability Discovery
    combined with the Capability Catalog's read-only retrieval/ranking
    pass (`parika.core.capability_catalog`), verified through the full
    live pipeline (InterfaceSession.submit_text() -> the actual
    `tools` array in the `/api/chat` HTTP payload). For a generic/
    ambiguous turn with no lexical signal (a greeting, an identity
    question), every enabled Capability is still advertised -- no
    domain/keyword routing, exactly as before the Catalog existed. For
    a turn with a genuine topical signal (e.g. a weather-specific
    question), Dynamic Relevance Cutoff narrows the roster to what is
    actually relevant. The two fixed-scope memory-authorization
    security gates (see `parika.interfaces.ai_context.tool_context.
    discover_tool_specs()`) still apply on top of whatever the Catalog
    retrieves, never capability routing.
    """

    def test_greeting_advertises_every_enabled_capability_except_memory_remember(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        transport.queue_chat_response(_simple_answer("Hi! How can I help?"))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("Hello!")

        advertised = transport.chat_payloads[0].get("tools", [])
        names = {tool["function"]["name"] for tool in advertised}

        assert "memory_remember" not in names
        assert "memory_search" in names
        assert "memory_forget" in names
        assert "get_current_datetime" in names
        assert "web_search" in names
        assert "weather_current" in names

    def test_identity_question_advertises_no_memory_tools(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        PARIKA Memory & Session Retrieval Finalization, Bug #2:
        identity questions must never invoke any memory tool.
        """

        transport.queue_chat_response(_simple_answer("I'm PARIKA."))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("Who are you?")

        advertised = transport.chat_payloads[0].get("tools", [])
        names = {tool["function"]["name"] for tool in advertised}

        assert "memory_remember" not in names
        assert "memory_search" not in names
        assert "memory_forget" not in names

    def test_identity_question_still_advertises_non_memory_capabilities(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        transport.queue_chat_response(_simple_answer("I'm PARIKA."))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("Who are you?")

        advertised = transport.chat_payloads[0].get("tools", [])
        names = {tool["function"]["name"] for tool in advertised}

        assert "web_search" in names
        assert "weather_current" in names
        assert "get_current_datetime" in names

    def test_weather_question_advertises_only_relevant_capabilities(
        self, runtime, transport: _ScriptedOllamaTransport
    ) -> None:
        """
        The Capability Catalog's Dynamic Relevance Cutoff (`parika.core
        .capability_catalog`) narrows the roster to what is genuinely
        relevant once a real lexical signal exists -- unlike a purely
        generic/ambiguous turn (see the greeting/identity tests above,
        which still defer to the full roster since they carry no
        signal at all), a specific, on-topic question like this one
        should no longer advertise an unrelated capability.
        """

        transport.queue_chat_response(_simple_answer("It's sunny."))

        session = InterfaceSession(runtime, system_prompt=None)
        session.submit_text("What's the weather like in Bengaluru?")

        advertised = transport.chat_payloads[0].get("tools", [])
        names = {tool["function"]["name"] for tool in advertised}

        assert "weather_current" in names
        assert "weather_forecast" in names
        assert "web_search" not in names
        assert "currency_convert" not in names
