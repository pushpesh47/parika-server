"""
PARIKA Runtime Info Module.

Registers the `runtime.current_datetime` Capability, backed by the
deterministic Runtime Info Tool.
"""

from .driver import RuntimeInfoModuleDriver
from .manifest import (
    RUNTIME_INFO_MODULE_ID,
    create_runtime_info_module,
    create_runtime_info_module_manifest,
)

__all__ = [
    "RUNTIME_INFO_MODULE_ID",
    "RuntimeInfoModuleDriver",
    "create_runtime_info_module",
    "create_runtime_info_module_manifest",
]
