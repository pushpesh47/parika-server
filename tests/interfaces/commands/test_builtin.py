"""
Unit tests for the built-in slash commands.

Exercised against a real `ParikaRuntime` (Ollama connectivity faked)
so command output reflects the real Core managers exactly as it would
in the CLI.
"""


from __future__ import annotations
from tests.conftest_db import build_test_db_config

from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from parika.interfaces.commands.builtin import create_default_registry
from parika.interfaces.history import HistoryRole
from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.interfaces.session import InterfaceSession
from parika.modules.chat.driver import CHAT_CAPABILITY_ID
from parika.tools.web_search.manifest import WEB_SEARCH_TOOL_ID
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


class _FakeOllamaTransport:
    def request_json(
        self, method: str, url: str, *, payload, timeout
    ) -> dict[str, Any]:
        if url.endswith("/api/tags"):
            return {"models": [{"name": "test-model"}]}
        if url.endswith("/api/show"):
            return {"capabilities": ["completion"]}
        if url.endswith("/api/version"):
            return {"version": "0.0.0-test"}
        return {}

    def stream_lines(
        self, method: str, url: str, *, payload, timeout
    ) -> Iterator[dict[str, Any]]:
        return iter(())


@pytest.fixture
def runtime(tmp_path, _test_db_pool):
    # Isolated, disposable data directory so tests exercising /memory
    # (or any other Memory/Knowledge/Experience-writing command) never
    # accumulate state in the real project's data/ directory.
    runtime = build_default_runtime(
        ollama_transport=_FakeOllamaTransport(),
        discover_comfyui_models=False,
        data_directory=tmp_path / "data",
        sync_pool=_test_db_pool,
    )
    yield runtime
    shutdown_runtime(runtime)


@pytest.fixture
def session(runtime) -> InterfaceSession:
    return InterfaceSession(runtime)


@pytest.fixture
def registry():
    return create_default_registry()


class TestHelp:
    def test_lists_every_builtin_command(self, registry, session) -> None:
        result = registry.dispatch("/help", session)

        for name in (
            "help", "status", "config", "modules", "providers", "tools",
            "capabilities", "history", "reload", "version", "clear", "exit",
        ):
            assert f"/{name}" in result.text


class TestStatus:
    def test_reports_active_modules_and_providers(
        self, registry, session
    ) -> None:
        result = registry.dispatch("/status", session)

        # 22 built-in Modules are registered and loaded (Web Search,
        # Runtime Info, Filesystem, Shell, Weather, Currency, News,
        # Expense Management, Chat, Knowledge Indexing, Experience,
        # Memory, Coding, Repository Intelligence, Coding Agent, OCR,
        # Vision, Document, Video, Generation, Voice, Media); Shell is
        # disabled by default (`[shell].enabled = false`) but is
        # still loaded/active - it simply registers zero
        # Capabilities/Tools while inert, exactly like a disabled
        # Filesystem Module would.
        assert "Modules: 22/22 active" in result.text
        assert "provider.ollama" in result.text

    def test_reports_memory_and_knowledge_before_any_turn(
        self, registry, session
    ) -> None:
        """
        Phase 1 Completion Specification section 18: runtime
        intelligence diagnostics must appear in `/status`, honestly
        reporting "n/a" (never fabricated) before any chat turn.
        """

        result = registry.dispatch("/status", session)

        assert "Memory:" in result.text
        assert "Permanent memories: 0" in result.text
        assert "Knowledge:" in result.text
        assert "Knowledge engines:" in result.text
        assert "Experience:" in result.text
        assert "Session:" in result.text
        assert "Planner:" in result.text
        assert "Selected provider: n/a" in result.text

    def test_reports_permanent_memory_count(self, registry, session) -> None:
        session.runtime.memory_manager.remember(content="A fact.")

        result = registry.dispatch("/status", session)

        assert "Permanent memories: 1" in result.text

    def test_reports_last_turn_diagnostics_after_a_chat_turn(
        self, registry, session
    ) -> None:
        session.runtime.memory_manager.remember(content="The user's name is Pushpesh.")
        session.submit_text("What is my name?")

        result = registry.dispatch("/status", session)

        assert "Memory hits: 1" in result.text
        assert "Advertised tools:" in result.text


class TestConfig:
    def test_returns_full_configuration_as_json(self, registry, session) -> None:
        result = registry.dispatch("/config", session)

        assert '"application"' in result.text

    def test_returns_single_key_value(self, registry, session) -> None:
        result = registry.dispatch("/config application.name", session)

        assert result.text.startswith("application.name = ")


class TestModules:
    def test_lists_registered_modules(self, registry, session) -> None:
        result = registry.dispatch("/modules", session)

        assert "web_search" in result.text
        assert "chat" in result.text
        assert "state=active" in result.text


class TestProviders:
    def test_lists_ollama_provider_and_model(self, registry, session) -> None:
        result = registry.dispatch("/providers", session)

        assert "provider.ollama" in result.text
        assert "test-model" in result.text


class TestTools:
    def test_lists_web_search_tool(self, registry, session) -> None:
        result = registry.dispatch("/tools", session)

        assert WEB_SEARCH_TOOL_ID in result.text


class TestCapabilities:
    def test_lists_web_search_and_chat_capabilities(
        self, registry, session
    ) -> None:
        result = registry.dispatch("/capabilities", session)

        assert "web.search" in result.text
        assert CHAT_CAPABILITY_ID in result.text


class TestHistory:
    def test_empty_history_message(self, registry, session) -> None:
        result = registry.dispatch("/history", session)

        assert result.text == "No history yet."

    def test_shows_recorded_entries(self, registry, session) -> None:
        session.record(HistoryRole.USER, "hello")

        result = registry.dispatch("/history", session)

        assert "hello" in result.text


class TestReload:
    def test_reloads_active_modules(self, registry, session) -> None:
        result = registry.dispatch("/reload", session)

        assert "web_search" in result.text
        assert "chat" in result.text

    def test_reconnects_registered_providers(self, registry, session) -> None:
        result = registry.dispatch("/reload", session)

        assert "Reconnected providers:" in result.text
        assert "provider.ollama" in result.text

    def test_reports_providers_that_fail_to_reconnect(
        self, registry, session
    ) -> None:
        from parika.providers.ollama.exceptions import OllamaConnectionError

        def _always_fails(provider_id):  # noqa: ANN001
            raise OllamaConnectionError("refused")

        session.runtime.provider_manager.discover_models = _always_fails

        result = registry.dispatch("/reload", session)

        assert "Providers still unavailable:" in result.text
        assert "provider.ollama" in result.text


class TestVersion:
    def test_reports_version(self, registry, session) -> None:
        result = registry.dispatch("/version", session)

        assert "PARIKA" in result.text


class TestClear:
    def test_clears_screen_and_history(self, registry, session) -> None:
        session.record(HistoryRole.USER, "hello")

        result = registry.dispatch("/clear", session)

        assert result.should_clear_screen
        assert session.history() == ()


class TestExit:
    def test_signals_exit(self, registry, session) -> None:
        result = registry.dispatch("/exit", session)

        assert result.should_exit
        assert result.text


class TestMemoryCommand:
    """
    Phase 1 Completion Specification section 10 ("/memory ...").
    """

    def test_bare_command_reports_no_memories(self, registry, session) -> None:
        result = registry.dispatch("/memory", session)

        assert "No permanent memories" in result.text

    def test_list_shows_remembered_facts(self, registry, session) -> None:
        session.runtime.memory_manager.remember(content="The user's name is Pushpesh.")

        result = registry.dispatch("/memory list", session)

        assert "Pushpesh" in result.text
        assert "category=" in result.text
        assert "importance=" in result.text
        assert "confidence=" in result.text

    def test_search_finds_matching_memory(self, registry, session) -> None:
        session.runtime.memory_manager.remember(content="The user's favorite color is blue.")
        session.runtime.memory_manager.remember(content="Unrelated fact about cooking.")

        result = registry.dispatch("/memory search favorite color", session)

        assert "blue" in result.text
        assert "cooking" not in result.text

    def test_search_without_query_shows_usage(self, registry, session) -> None:
        result = registry.dispatch("/memory search", session)

        assert "Usage:" in result.text

    def test_delete_removes_memory(self, registry, session) -> None:
        memory, _ = session.runtime.memory_manager.remember(content="Temporary fact.")

        result = registry.dispatch(f"/memory delete {memory.memory_id}", session)

        assert "Deleted" in result.text
        assert not session.runtime.memory_manager.contains(memory.memory_id)

    def test_delete_unknown_id_reports_not_found(self, registry, session) -> None:
        result = registry.dispatch("/memory delete nonexistent", session)

        assert "not found" in result.text.lower()

    def test_clear_without_confirmation_does_not_delete(self, registry, session) -> None:
        session.runtime.memory_manager.remember(content="A fact.")

        result = registry.dispatch("/memory clear", session)

        assert "confirm" in result.text.lower()
        assert session.runtime.memory_manager.count() == 1

    def test_clear_confirm_deletes_everything(self, registry, session) -> None:
        session.runtime.memory_manager.remember(content="A fact.")
        session.runtime.memory_manager.remember(content="Another fact.")

        result = registry.dispatch("/memory clear confirm", session)

        assert "Cleared 2" in result.text
        assert session.runtime.memory_manager.count() == 0

    def test_stats_reports_totals_and_breakdown(self, registry, session) -> None:
        from parika.core.memory_manager.memory_category import MemoryCategory

        session.runtime.memory_manager.remember(
            content="A profile fact.", category=MemoryCategory.PROFILE
        )

        result = registry.dispatch("/memory stats", session)

        assert "Permanent memories: 1" in result.text
        assert "profile: 1" in result.text

    def test_export_writes_a_file(self, registry, session, tmp_path) -> None:
        session.runtime.memory_manager.remember(content="An exportable fact.")
        export_path = tmp_path / "export.json"

        result = registry.dispatch(f"/memory export {export_path}", session)

        assert "Exported 1" in result.text
        assert export_path.exists()

    def test_import_restores_memories(self, registry, session, tmp_path) -> None:
        session.runtime.memory_manager.remember(content="A fact to export.")
        export_path = tmp_path / "export.json"
        session.runtime.memory_manager.export(export_path)
        session.runtime.memory_manager.clear()

        result = registry.dispatch(f"/memory import {export_path}", session)

        assert "Imported 1" in result.text
        assert session.runtime.memory_manager.count() == 1

    def test_import_without_path_shows_usage(self, registry, session) -> None:
        result = registry.dispatch("/memory import", session)

        assert "Usage:" in result.text

    def test_unknown_subcommand_reports_error(self, registry, session) -> None:
        result = registry.dispatch("/memory bogus", session)

        assert "Unknown" in result.text


class TestSessionsCommand:
    """
    Phase 1 Completion Specification section 17 ("/sessions ...").
    """

    @pytest.fixture
    def session_with_store(self, runtime, tmp_path, _test_db_pool):
        from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore

        store = PostgreSQLSessionStore(_test_db_pool)
        store.initialize()

        return InterfaceSession(
            runtime, system_prompt=None, session_id="s1", session_store=store
        )

    def test_reports_disabled_when_no_store(self, registry, session) -> None:
        result = registry.dispatch("/sessions", session)

        assert "not enabled" in result.text.lower()

    def test_rename_updates_title(self, registry, session_with_store) -> None:
        result = registry.dispatch("/sessions rename s1 My Title", session_with_store)

        assert "Renamed" in result.text
        summary = session_with_store.session_store.get_session("s1")
        assert summary.title == "My Title"

    def test_rename_missing_session_reports_error(
        self, registry, session_with_store
    ) -> None:
        result = registry.dispatch("/sessions rename missing Title", session_with_store)

        assert "was not found" in result.text

    def test_rename_without_title_shows_usage(self, registry, session_with_store) -> None:
        result = registry.dispatch("/sessions rename s1", session_with_store)

        assert "Usage:" in result.text

    def test_delete_removes_session(self, registry, session_with_store) -> None:
        result = registry.dispatch("/sessions delete s1", session_with_store)

        assert "Deleted" in result.text
        assert session_with_store.session_store.get_session("s1") is None

    def test_delete_missing_session_reports_not_found(
        self, registry, session_with_store
    ) -> None:
        result = registry.dispatch("/sessions delete missing", session_with_store)

        assert "not found" in result.text

    def test_export_writes_file(self, registry, session_with_store, tmp_path) -> None:
        export_path = tmp_path / "out.json"

        result = registry.dispatch(f"/sessions export s1 {export_path}", session_with_store)

        assert "Exported" in result.text
        assert export_path.exists()

    def test_export_missing_session_reports_error(
        self, registry, session_with_store, tmp_path
    ) -> None:
        result = registry.dispatch(
            f"/sessions export missing {tmp_path / 'x.json'}", session_with_store
        )

        assert "was not found" in result.text

    def test_import_restores_session(self, registry, session_with_store, tmp_path) -> None:
        export_path = tmp_path / "out.json"
        session_with_store.session_store.export_session("s1", path=export_path)
        session_with_store.session_store.delete_session("s1")

        result = registry.dispatch(f"/sessions import {export_path}", session_with_store)

        assert "Imported" in result.text

    def test_import_without_path_shows_usage(self, registry, session_with_store) -> None:
        result = registry.dispatch("/sessions import", session_with_store)

        assert "Usage:" in result.text

    def test_unknown_subcommand_reports_error(self, registry, session_with_store) -> None:
        result = registry.dispatch("/sessions bogus", session_with_store)

        assert "Unknown" in result.text
