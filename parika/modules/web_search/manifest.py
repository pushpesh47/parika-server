"""
PARIKA Web Search Module - Manifest

Defines the static ModuleManifest describing the Web Search Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import WebSearchModuleDriver

WEB_SEARCH_MODULE_ID = "web_search"
WEB_SEARCH_MODULE_VERSION = "1.0.0"


def create_web_search_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Web Search Module.
    """

    return ModuleManifest(
        id=WEB_SEARCH_MODULE_ID,
        name="Web Search",
        version=WEB_SEARCH_MODULE_VERSION,
        description=(
            "Provides the web.search Capability: searching the web "
            "and optionally fetching and extracting the readable "
            "content of each result page."
        ),
        author="PARIKA",
        license="MIT",
        tags=("web", "search", "network"),
        required_permissions=("network.fetch",),
        driver=(
            "parika.modules.web_search.driver.WebSearchModuleDriver"
        ),
    )


def create_web_search_module(driver: WebSearchModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Web Search Module.

    Args:
        driver:
            Constructed WebSearchModuleDriver instance for this
            module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=WEB_SEARCH_MODULE_ID,
        manifest=create_web_search_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
