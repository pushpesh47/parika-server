"""
Observability tests for `Planner.plan()`.

Verifies the additive DEBUG logging added for this milestone (planning
duration and the generated plan's steps) without touching
`test_planner.py` (frozen, unmodified).
"""

from __future__ import annotations

import logging

import pytest

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager


class _NoopToolDriver:
    def execute(self, request):  # noqa: ANN001, ANN201
        from parika.core.tool_manager.response import ToolResponse

        return ToolResponse(result="ok")


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    return EventBus(logger=logger)


@pytest.fixture
def capability_registry(event_bus: EventBus, logger: Logger) -> CapabilityRegistry:
    registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
    registry.register(
        CapabilityDefinition(
            id="tool.example",
            name="Example Tool",
            description="Example.",
            category=CapabilityCategory.TOOL,
        )
    )
    return registry


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger, capability_registry) -> ToolManager:
    manager = ToolManager(event_bus=event_bus, logger=logger)
    manager.register(
        Tool(
            id="tool.example.driver",
            name="Example",
            version="1.0.0",
            description="Example.",
            capabilities=("tool.example",),
        ),
        _NoopToolDriver(),
    )
    return manager


@pytest.fixture
def planner(
    capability_registry: CapabilityRegistry,
    tool_manager: ToolManager,
    logger: Logger,
    event_bus: EventBus,
) -> Planner:
    return Planner(
        capability_resolver=CapabilityResolver(
            capability_registry=capability_registry, logger=logger
        ),
        resource_manager=ResourceManager(
            configuration=Configuration(), logger=logger
        ),
        policy_engine=PolicyEngine(event_bus=event_bus, logger=logger),
        provider_manager=ProviderManager(event_bus=event_bus, logger=logger),
        tool_manager=tool_manager,
        logger=logger,
    )


class TestPlanningObservability:
    def test_logs_planning_duration_and_generated_steps(
        self, planner: Planner, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(
            logging.DEBUG, logger="parika.core.planner.planner"
        ):
            planner.plan([Goal(id="g1", capability_id="tool.example")])

        assert "planning_duration_ms=" in caplog.text
        assert "g1" in caplog.text
        assert "tool.example" in caplog.text
        assert "tool" in caplog.text  # ExecutionBackend.TOOL.value
