"""
Unit tests for MemoryToolDriver (memory.remember/search/forget).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.tool_manager.request import ToolRequest
from parika.tools.memory.driver import MemoryToolDriver, MemoryToolOperation
from parika.tools.memory.exceptions import InvalidMemoryToolArgumentError


class _FakeConfiguration:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


_ASSISTANT_CONFIGURATION = _FakeConfiguration(
    {
        "assistant.name": "PARIKA",
        "assistant.full_name": "Personal Adaptive Responsive Intelligence Kernel Assistant",
        "assistant.nick_name": "PARI",
    }
)


@pytest.fixture
def memory_manager(
    logger: Logger, event_bus: EventBus, tmp_path: Path
) -> Iterator[MemoryManager]:
    manager = MemoryManager(
        logger=logger, event_bus=event_bus, database_path=tmp_path / "memory.db"
    )
    manager.initialize()

    yield manager

    manager.shutdown()


class TestRemember:
    def test_stores_a_new_memory(self, memory_manager: MemoryManager) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        response = driver.execute(
            ToolRequest(arguments={"content": "My name is Pushpesh."})
        )

        assert response.result["stored"] is True
        assert response.result["created"] is True
        assert memory_manager.count() == 1

    def test_rejects_empty_content(self, memory_manager: MemoryManager) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        with pytest.raises(InvalidMemoryToolArgumentError):
            driver.execute(ToolRequest(arguments={"content": "  "}))

    def test_auto_categorizes_when_category_omitted(
        self, memory_manager: MemoryManager
    ) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        response = driver.execute(
            ToolRequest(arguments={"content": "I prefer dark mode."})
        )

        assert response.result["category"] == "preference"

    def test_respects_explicit_category_override(
        self, memory_manager: MemoryManager
    ) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        response = driver.execute(
            ToolRequest(arguments={"content": "I prefer dark mode.", "category": "custom"})
        )

        assert response.result["category"] == "custom"

    def test_respects_explicit_importance(self, memory_manager: MemoryManager) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        response = driver.execute(
            ToolRequest(arguments={"content": "Critical fact.", "importance": "critical"})
        )

        assert response.result["importance"] == "critical"

    def test_second_remember_of_same_fact_merges_not_duplicates(
        self, memory_manager: MemoryManager
    ) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        driver.execute(ToolRequest(arguments={"content": "My name is Pushpesh."}))
        response = driver.execute(ToolRequest(arguments={"content": "My name is Pushpesh"}))

        assert response.result["created"] is False
        assert memory_manager.count() == 1


class TestAssistantIdentityProtection:
    """
    PARIKA Memory Subsystem Refactor Requirement A: `memory.remember`
    must never persist Assistant Identity content, regardless of what
    a model was instructed to do -- this is the deterministic, driver-
    level backstop for that requirement (see `identity_guard.py`).
    """

    def test_rejects_content_naming_the_assistant(
        self, memory_manager: MemoryManager
    ) -> None:
        driver = MemoryToolDriver(
            MemoryToolOperation.REMEMBER,
            memory_manager=memory_manager,
            configuration=_ASSISTANT_CONFIGURATION,
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "content": "PARIKA was created by Pushpesh Sharma from Independent."
                }
            )
        )

        assert response.result["stored"] is False
        assert response.result["reason"] == "assistant_identity_protected"
        assert memory_manager.count() == 0

    def test_rejects_self_referential_creator_statement_without_configuration(
        self, memory_manager: MemoryManager
    ) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        response = driver.execute(
            ToolRequest(arguments={"content": "I was created by Pushpesh Sharma."})
        )

        assert response.result["stored"] is False
        assert memory_manager.count() == 0

    def test_still_stores_an_ordinary_user_fact(
        self, memory_manager: MemoryManager
    ) -> None:
        driver = MemoryToolDriver(
            MemoryToolOperation.REMEMBER,
            memory_manager=memory_manager,
            configuration=_ASSISTANT_CONFIGURATION,
        )

        response = driver.execute(
            ToolRequest(arguments={"content": "My name is Pushpesh Sharma."})
        )

        assert response.result["stored"] is True
        assert memory_manager.count() == 1


class TestPrecisionStorage:
    """
    PARIKA Memory Subsystem Refactor Requirement C: an explicit-memory
    instruction verb (e.g. "remember that", "save this:", "don't
    forget") accidentally left in `content` is stripped before
    storage, so the memory itself never carries the instruction, only
    the actual information.
    """

    def test_strips_remember_that_prefix(self, memory_manager: MemoryManager) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        driver.execute(
            ToolRequest(arguments={"content": "Remember that Docker is useful."})
        )

        stored = memory_manager.get_all()[0]
        assert stored.content == "Docker is useful."

    def test_strips_save_this_prefix(self, memory_manager: MemoryManager) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        driver.execute(
            ToolRequest(arguments={"content": "Save this: Docker is useful."})
        )

        stored = memory_manager.get_all()[0]
        assert stored.content == "Docker is useful."

    def test_leaves_precise_content_untouched(
        self, memory_manager: MemoryManager
    ) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.REMEMBER, memory_manager=memory_manager)

        driver.execute(ToolRequest(arguments={"content": "Docker is useful."}))

        stored = memory_manager.get_all()[0]
        assert stored.content == "Docker is useful."


class TestSearch:
    def test_finds_remembered_fact(self, memory_manager: MemoryManager) -> None:
        memory_manager.remember(content="The user's favorite color is blue.")

        driver = MemoryToolDriver(MemoryToolOperation.SEARCH, memory_manager=memory_manager)
        response = driver.execute(ToolRequest(arguments={"query": "favorite color"}))

        assert len(response.result["matches"]) == 1
        assert "blue" in response.result["matches"][0]["content"]

    def test_rejects_empty_query(self, memory_manager: MemoryManager) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.SEARCH, memory_manager=memory_manager)

        with pytest.raises(InvalidMemoryToolArgumentError):
            driver.execute(ToolRequest(arguments={"query": ""}))

    def test_respects_limit(self, memory_manager: MemoryManager) -> None:
        for i in range(5):
            memory_manager.remember(content=f"distinct memory number {i}")

        driver = MemoryToolDriver(MemoryToolOperation.SEARCH, memory_manager=memory_manager)
        response = driver.execute(ToolRequest(arguments={"query": "distinct", "limit": 2}))

        assert len(response.result["matches"]) == 2


class TestForget:
    def test_forgets_by_memory_id(self, memory_manager: MemoryManager) -> None:
        memory, _ = memory_manager.remember(content="Temporary fact.")

        driver = MemoryToolDriver(MemoryToolOperation.FORGET, memory_manager=memory_manager)
        response = driver.execute(ToolRequest(arguments={"memory_id": memory.memory_id}))

        assert response.result["forgotten"] is True
        assert not memory_manager.contains(memory.memory_id)

    def test_forgets_by_query_match(self, memory_manager: MemoryManager) -> None:
        memory_manager.remember(content="The user's favorite color is blue.")

        driver = MemoryToolDriver(MemoryToolOperation.FORGET, memory_manager=memory_manager)
        response = driver.execute(ToolRequest(arguments={"query": "favorite color"}))

        assert response.result["forgotten"] is True
        assert memory_manager.count() == 0

    def test_reports_not_found_for_unknown_memory_id(
        self, memory_manager: MemoryManager
    ) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.FORGET, memory_manager=memory_manager)

        response = driver.execute(ToolRequest(arguments={"memory_id": "missing"}))

        assert response.result["forgotten"] is False

    def test_requires_memory_id_or_query(self, memory_manager: MemoryManager) -> None:
        driver = MemoryToolDriver(MemoryToolOperation.FORGET, memory_manager=memory_manager)

        with pytest.raises(InvalidMemoryToolArgumentError):
            driver.execute(ToolRequest(arguments={}))
