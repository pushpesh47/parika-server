"""
PARIKA Coding Agent Module - Driver

Implements the `ModuleDriver` contract for the Coding Agent Module.

On start(), registers:
- `coding.execute_task` (`CapabilityCategory.AUTOMATION`) with its
  `tool.coding_execute_task` Tool.
- `coding.plan_change` (`CapabilityCategory.LLM`) -- satisfied by a
  Provider model, not a Tool, exactly like `chat.respond`.

On stop(), unregisters both.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.brain.brain import Brain
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.event_bus.event_bus import EventBus
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressReporter

from .agent import CodingAgent
from .driver import CodingAgentToolDriver
from .registry import CodingAgentRegistry
from .standard_agent import PLAN_CHANGE_CAPABILITY_ID, StandardCodingAgent

EXECUTE_TASK_CAPABILITY_ID = "coding.execute_task"
EXECUTE_TASK_TOOL_ID = "tool.coding_execute_task"
CODING_AGENT_TOOL_VERSION = "1.0.0"

DEFAULT_MAX_DEPTH = 3
DEFAULT_REQUIRE_TEST_RUN = False
DEFAULT_AGENT_ID = "standard"

MODULE_HEALTH_COMPONENT_ID = "module.coding_agent"


class CodingAgentModuleDriver(ModuleDriver):
    """
    Runtime driver for the Coding Agent Module.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        brain: Brain,
        logger: Logger,
        default_workspace: Path,
        event_bus: EventBus | None = None,
        health_manager: HealthManager | None = None,
        configuration: Configuration | None = None,
        extra_agents: tuple[CodingAgent, ...] = (),
    ) -> None:
        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)

        self._enabled = bool(
            (configuration or Configuration()).get("coding_agent.enabled", True)
        )
        self._max_depth = int(
            (configuration or Configuration()).get(
                "coding_agent.default_max_depth", DEFAULT_MAX_DEPTH
            )
        )
        self._require_test_run = bool(
            (configuration or Configuration()).get(
                "coding_agent.require_test_run", DEFAULT_REQUIRE_TEST_RUN
            )
        )
        raw_allowed_roots = (configuration or Configuration()).get(
            "coding_agent.allowed_write_roots", []
        )
        self._allowed_write_roots = tuple(Path(str(p)) for p in raw_allowed_roots)
        self._default_agent_id = str(
            (configuration or Configuration()).get(
                "coding_agent.default_agent", DEFAULT_AGENT_ID
            )
        )

        standard_agent = StandardCodingAgent(
            brain=brain, capability_registry=capability_registry
        )
        registry = CodingAgentRegistry((*extra_agents, standard_agent))
        self._registry = registry

        self._tool_driver = CodingAgentToolDriver(
            registry=registry,
            default_workspace=default_workspace,
            default_max_depth=self._max_depth,
            allowed_write_roots=self._allowed_write_roots,
            require_test_run=self._require_test_run,
            progress_reporter=(
                ProgressReporter(event_bus, EXECUTE_TASK_CAPABILITY_ID)
                if event_bus is not None
                else None
            ),
        )

    @property
    def registry(self) -> CodingAgentRegistry:
        return self._registry

    def start(self) -> None:
        if not self._enabled:
            self._logger.info(
                "Coding Agent module is disabled by configuration; "
                "not registering its Capabilities or Tool."
            )
            return

        self._capability_registry.register(
            CapabilityDefinition(
                id=EXECUTE_TASK_CAPABILITY_ID,
                name="Coding Agent - Execute Task",
                description=(
                    "Orchestrates Planner, the Coding Tool, the "
                    "Filesystem Tool, and the Shell Tool to carry out "
                    "a natural-language coding request end to end."
                ),
                # TOOL, not AUTOMATION: Planner routes a Goal to
                # ToolManager only when `category is
                # CapabilityCategory.TOOL` (every other category is
                # assumed to require a Provider model). This
                # Capability is backed by a real, deterministic-
                # dispatch ToolDriver (`CodingAgentToolDriver`), so it
                # must be TOOL for Planner to ever select it -- the
                # "automation" tag still conveys its orchestrating
                # nature without changing its execution backend.
                category=CapabilityCategory.TOOL,
                tags=frozenset({"coding", "agent", "automation"}),
                metadata={  # type: ignore[arg-type]
                    "decomposition_terminal": True,
                },
            )
        )
        self._tool_manager.register(
            Tool(
                id=EXECUTE_TASK_TOOL_ID,
                name="Coding Agent",
                version=CODING_AGENT_TOOL_VERSION,
                description="Orchestrates a coding request end to end.",
                capabilities=(EXECUTE_TASK_CAPABILITY_ID,),
            ),
            self._tool_driver,
        )

        self._capability_registry.register(
            CapabilityDefinition(
                id=PLAN_CHANGE_CAPABILITY_ID,
                name="Coding Agent - Plan Change",
                description=(
                    "AI-reasoning decomposition of a coding request "
                    "into a structured, capability-targeting plan."
                ),
                category=CapabilityCategory.LLM,
                tags=frozenset({"coding", "agent", "planning"}),
            )
        )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Coding Agent module started.")

    def stop(self) -> None:
        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._tool_manager.unregister(EXECUTE_TASK_TOOL_ID)
        self._capability_registry.unregister(EXECUTE_TASK_CAPABILITY_ID)
        self._capability_registry.unregister(PLAN_CHANGE_CAPABILITY_ID)

        self._logger.info("Coding Agent module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
