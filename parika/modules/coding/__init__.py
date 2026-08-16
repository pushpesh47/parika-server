"""
PARIKA Coding Module package.

Registers every `coding.*` Capability and its Coding Tool with
CapabilityRegistry/ToolManager. See
docs/development/Module_Guide.md section 4.
"""

from __future__ import annotations

from .driver import CodingModuleDriver
from .manifest import (
    CODING_MODULE_ID,
    CODING_MODULE_VERSION,
    create_coding_module,
    create_coding_module_manifest,
)

__all__ = [
    "CODING_MODULE_ID",
    "CODING_MODULE_VERSION",
    "CodingModuleDriver",
    "create_coding_module",
    "create_coding_module_manifest",
]
