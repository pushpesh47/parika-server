"""
PARIKA Web Search Module package.

Integrates the Web Search Tool into PARIKA through ModuleManager,
CapabilityRegistry, and ToolManager.
"""

from .driver import MODULE_HEALTH_COMPONENT_ID, WebSearchModuleDriver
from .manifest import (
    WEB_SEARCH_MODULE_ID,
    WEB_SEARCH_MODULE_VERSION,
    create_web_search_module,
    create_web_search_module_manifest,
)

__all__ = [
    "MODULE_HEALTH_COMPONENT_ID",
    "WEB_SEARCH_MODULE_ID",
    "WEB_SEARCH_MODULE_VERSION",
    "WebSearchModuleDriver",
    "create_web_search_module",
    "create_web_search_module_manifest",
]
