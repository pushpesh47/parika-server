"""
PARIKA Currency Module - Manifest

Defines the static ModuleManifest describing the Currency Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import CurrencyModuleDriver

CURRENCY_MODULE_ID = "currency"
CURRENCY_MODULE_VERSION = "1.0.0"


def create_currency_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Currency Module.
    """

    return ModuleManifest(
        id=CURRENCY_MODULE_ID,
        name="Currency",
        version=CURRENCY_MODULE_VERSION,
        description=(
            "Provides the currency.exchange_rate and "
            "currency.convert Capabilities using Frankfurter, with "
            "automatic failover to open.er-api.com."
        ),
        author="PARIKA",
        license="MIT",
        tags=("currency", "network"),
        required_permissions=("network.fetch",),
        driver=(
            "parika.modules.currency.driver.CurrencyModuleDriver"
        ),
    )


def create_currency_module(driver: CurrencyModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Currency Module.

    Args:
        driver:
            Constructed CurrencyModuleDriver instance for this
            module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=CURRENCY_MODULE_ID,
        manifest=create_currency_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
