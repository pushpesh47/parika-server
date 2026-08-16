"""
PARIKA News Module package.

Integrates the News Tool into PARIKA through ModuleManager,
CapabilityRegistry, and ToolManager.
"""

from __future__ import annotations

from .driver import MODULE_HEALTH_COMPONENT_ID, NewsModuleDriver
from .manifest import (
    NEWS_MODULE_ID,
    NEWS_MODULE_VERSION,
    create_news_module,
    create_news_module_manifest,
)

__all__ = [
    "MODULE_HEALTH_COMPONENT_ID",
    "NEWS_MODULE_ID",
    "NEWS_MODULE_VERSION",
    "NewsModuleDriver",
    "create_news_module",
    "create_news_module_manifest",
]
