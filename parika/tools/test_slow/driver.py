"""
PARIKA Test Slow Tool - Driver

Implements the test.slow_operation capability. Simply sleeps for a
configurable duration to simulate a long-running operation.
"""

from __future__ import annotations

import time
from typing import Any

from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.logger.logger import Logger


# Define constants locally to avoid circular imports
TEST_SLOW_OPERATION_CAPABILITY_ID = "test.slow_operation"
TEST_SLOW_OPERATION_NAME = "Test Slow Operation"
TEST_SLOW_OPERATION_DESCRIPTION = (
    "A test capability that sleeps for a configurable duration "
    "to simulate a long-running operation."
)
TEST_SLOW_TOOL_ID = "tool.test_slow_operation"
TEST_SLOW_TOOL_NAME = "Test Slow Operation"
TEST_SLOW_TOOL_VERSION = "1.0.0"


def create_test_slow_tool() -> Tool:
    """Create the test slow tool."""
    return Tool(
        id=TEST_SLOW_TOOL_ID,
        name=TEST_SLOW_TOOL_NAME,
        version=TEST_SLOW_TOOL_VERSION,
        description=TEST_SLOW_OPERATION_DESCRIPTION,
        capabilities=(TEST_SLOW_OPERATION_CAPABILITY_ID,),
    )


class TestSlowModuleDriver(ModuleDriver):
    """
    Driver for the test_slow module.
    
    Provides the test.slow_operation capability that sleeps for a
    configurable duration.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        default_delay: float = 0.0,
    ) -> None:
        """
        Initialize the driver.

        Args:
            capability_registry:
                Registry used to register/unregister the capability.
            tool_manager:
                Manager used to register/unregister the tool.
            logger:
                PARIKA Logger component.
            default_delay:
                Default delay in seconds if not specified in the request.
        """
        self.default_delay = default_delay
        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._logger = logger.get_logger(__name__)
        self._tool: Tool | None = None

    def start(self) -> None:
        """Register the test slow tool and capability."""
        # Create and register the tool
        self._tool = create_test_slow_tool()

        self._capability_registry.register(
            CapabilityDefinition(
                id=TEST_SLOW_OPERATION_CAPABILITY_ID,
                name=TEST_SLOW_OPERATION_NAME,
                description=TEST_SLOW_OPERATION_DESCRIPTION,
                category=CapabilityCategory.TOOL,
                tags=frozenset({"test", "concurrency"}),
            )
        )

        self._tool_manager.register(self._tool, self)

        self._logger.info("Test Slow module started.")

    def stop(self) -> None:
        """Unregister the test slow tool and capability."""
        if self._tool:
            self._tool_manager.unregister(self._tool.id)
        self._capability_registry.unregister(TEST_SLOW_OPERATION_CAPABILITY_ID)
        self._tool = None

        self._logger.info("Test Slow module stopped.")

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Execute the slow operation.

        Args:
            request:
                Tool request with optional `delay_seconds` argument.

        Returns:
            Tool response with the delay that was used.
        """
        # Get delay from request arguments or use default
        delay_seconds = request.arguments.get("delay_seconds", self.default_delay)

        # Validate delay
        if not isinstance(delay_seconds, (int, float)) or delay_seconds < 0:
            delay_seconds = self.default_delay

        # Cap at a reasonable maximum for tests
        delay_seconds = min(delay_seconds, 60.0)

        # Sleep for the specified duration
        time.sleep(delay_seconds)

        return ToolResponse(
            result={
                "status": "completed",
                "delay_seconds": delay_seconds,
                "message": f"Slow operation completed after {delay_seconds:.2f} seconds",
            },
            attributes={
                "capability_id": TEST_SLOW_OPERATION_CAPABILITY_ID,
                "delay_seconds": delay_seconds,
            },
        )