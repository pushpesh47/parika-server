"""
PARIKA Currency Module package.

Integrates the Currency Tool into PARIKA through ModuleManager,
CapabilityRegistry, and ToolManager.
"""

from __future__ import annotations

from .driver import MODULE_HEALTH_COMPONENT_ID, CurrencyModuleDriver
from .manifest import (
    CURRENCY_MODULE_ID,
    CURRENCY_MODULE_VERSION,
    create_currency_module,
    create_currency_module_manifest,
)

__all__ = [
    "CURRENCY_MODULE_ID",
    "CURRENCY_MODULE_VERSION",
    "MODULE_HEALTH_COMPONENT_ID",
    "CurrencyModuleDriver",
    "create_currency_module",
    "create_currency_module_manifest",
]
