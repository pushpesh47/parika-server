"""
Unit tests for CodingModuleDriver.

Uses the shared `logger`/`event_bus` fixtures from `tests/conftest.py`,
since `CapabilityRegistry`/`ToolManager` strictly type-check `Logger`/
`EventBus` and reject fakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.coding.driver import CodingModuleDriver
from parika.tools.coding.manifest import CODING_OPERATIONS


@pytest.fixture()
def driver(tmp_path: Path, logger: Logger, event_bus: EventBus) -> CodingModuleDriver:
    capability_registry = CapabilityRegistry(event_bus, logger)
    tool_manager = ToolManager(event_bus, logger)

    instance = CodingModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        database_path=tmp_path / "coding_index.sqlite3",
        event_bus=event_bus,
    )
    instance.start()
    yield instance
    instance.stop()


def test_start_registers_every_capability_and_tool(driver: CodingModuleDriver) -> None:
    for spec in CODING_OPERATIONS:
        assert driver._capability_registry.contains(spec.capability_id)  # type: ignore[attr-defined]
        assert driver._tool_manager.contains(spec.tool_id)  # type: ignore[attr-defined]


def test_symbols_capability_is_executable_end_to_end(
    driver: CodingModuleDriver, tmp_path: Path
) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    response = driver._tool_manager.execute(  # type: ignore[attr-defined]
        "tool.coding_symbols",
        ToolRequest(arguments={"path": str(sample)}),
    )

    names = {symbol["qualified_name"] for symbol in response.result}
    assert "sample.greet" in names


def test_progress_events_are_published_for_symbols(
    driver: CodingModuleDriver, tmp_path: Path
) -> None:
    captured: list[str] = []
    driver._event_bus.subscribe(  # type: ignore[attr-defined]
        "progress.started", lambda event: captured.append(event.source_id)
    )

    sample = tmp_path / "sample.py"
    sample.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    driver._tool_manager.execute(  # type: ignore[attr-defined]
        "tool.coding_symbols",
        ToolRequest(arguments={"path": str(sample)}),
    )

    assert "coding.symbols" in captured


def test_stop_unregisters_everything(
    tmp_path: Path, logger: Logger, event_bus: EventBus
) -> None:
    capability_registry = CapabilityRegistry(event_bus, logger)
    tool_manager = ToolManager(event_bus, logger)

    instance = CodingModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        database_path=tmp_path / "coding_index.sqlite3",
    )
    instance.start()
    instance.stop()

    for spec in CODING_OPERATIONS:
        assert not capability_registry.contains(spec.capability_id)
        assert not tool_manager.contains(spec.tool_id)


def test_disabled_module_registers_nothing(
    tmp_path: Path, logger: Logger, event_bus: EventBus
) -> None:
    capability_registry = CapabilityRegistry(event_bus, logger)
    tool_manager = ToolManager(event_bus, logger)

    class _DisabledConfiguration(Configuration):
        def get(self, key: str, default=None):
            if key == "coding.enabled":
                return False
            return super().get(key, default)

    instance = CodingModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        database_path=tmp_path / "coding_index.sqlite3",
        configuration=_DisabledConfiguration(),
    )
    instance.start()

    assert capability_registry.get_all() == ()
    assert tool_manager.get_all() == ()

    instance.stop()
