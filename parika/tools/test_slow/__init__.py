"""
PARIKA Test Slow Tool - Package Init
"""

from __future__ import annotations

from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.logger.logger import Logger

from .manifest import (
    TEST_SLOW_OPERATION_CAPABILITY_ID,
    TEST_SLOW_OPERATION_NAME,
    TEST_SLOW_OPERATION_DESCRIPTION,
    TEST_SLOW_MODULE_ID,
    TEST_SLOW_MODULE_VERSION,
    create_test_slow_module_manifest,
    create_test_slow_module,
)
from .driver import TestSlowModuleDriver, create_test_slow_tool

__all__ = [
    "TEST_SLOW_OPERATION_CAPABILITY_ID",
    "TEST_SLOW_OPERATION_NAME",
    "TEST_SLOW_OPERATION_DESCRIPTION",
    "TEST_SLOW_MODULE_ID",
    "TEST_SLOW_MODULE_VERSION",
    "create_test_slow_module_manifest",
    "create_test_slow_module",
    "create_test_slow_tool",
    "TestSlowModuleDriver",
]