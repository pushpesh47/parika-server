"""
PARIKA Capability Execution Backends.

Defines the supported execution backends for CapabilityExecutor.
"""

from enum import StrEnum


class ExecutionBackend(StrEnum):
    """
    Supported execution backends.

    TOOL:
        Execute using ToolManager.

    PROVIDER:
        Execute using ProviderManager.
    """

    TOOL = "tool"
    PROVIDER = "provider"