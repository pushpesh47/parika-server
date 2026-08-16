"""
PARIKA News Module - Manifest

Defines the static ModuleManifest describing the News Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import NewsModuleDriver

NEWS_MODULE_ID = "news"
NEWS_MODULE_VERSION = "1.0.0"


def create_news_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the News Module.
    """

    return ModuleManifest(
        id=NEWS_MODULE_ID,
        name="News",
        version=NEWS_MODULE_VERSION,
        description=(
            "Provides the news.latest, news.search, and news.topic "
            "Capabilities using RSS/Atom aggregation of no-API-key "
            "sources."
        ),
        author="PARIKA",
        license="MIT",
        tags=("news", "network"),
        required_permissions=("network.fetch",),
        driver="parika.modules.news.driver.NewsModuleDriver",
    )


def create_news_module(driver: NewsModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the News Module.

    Args:
        driver:
            Constructed NewsModuleDriver instance for this module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=NEWS_MODULE_ID,
        manifest=create_news_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
