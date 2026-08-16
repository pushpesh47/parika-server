"""
PARIKA API - Configuration and Reload Handlers

`/api/v1/config` is read-only, mirroring `/config`; `/api/v1/reload`
re-triggers Module reload and provider reconnect, mirroring `/reload`
exactly (see `parika/interfaces/commands/builtin.py`).
"""

from __future__ import annotations

from typing import Any

from parika.interfaces.runtime import ParikaRuntime

from ..requests import ConfigGetRequest, ReloadRequest


def handle_config_get(runtime: ParikaRuntime, request: ConfigGetRequest) -> dict[str, Any]:
    """
    Return the merged, read-only Configuration -- either the entire
    tree, or a single key when `request.key` is supplied.
    """

    if request.key:
        return {"key": request.key, "value": runtime.configuration.get(request.key)}

    return {"key": None, "value": runtime.configuration.all()}


def handle_reload(runtime: ParikaRuntime, request: ReloadRequest) -> dict[str, Any]:
    """
    Reload every active Module, then re-run model discovery and a
    health refresh for every registered Provider -- byte-for-byte the
    same orchestration as the existing `/reload` slash command
    (`parika/interfaces/commands/builtin.py:_handle_reload`), moved
    here unchanged so both surfaces share one implementation.
    """

    module_manager = runtime.module_manager
    provider_manager = runtime.provider_manager

    reloaded_modules: list[str] = []

    for module in module_manager.get_active():
        module_manager.unload(module.id)
        module_manager.load(module.id)
        reloaded_modules.append(module.id)

    reconnected_providers: list[str] = []
    failed_providers: list[str] = []

    for provider in provider_manager.get_all():
        try:
            provider_manager.discover_models(provider.id)
            provider_manager.refresh_health(provider.id)
            reconnected_providers.append(provider.id)

        except Exception as ex:  # noqa: BLE001 - best-effort reconnect
            failed_providers.append(f"{provider.id} ({ex})")

    return {
        "reloaded_modules": sorted(reloaded_modules),
        "reconnected_providers": sorted(reconnected_providers),
        "failed_providers": failed_providers,
    }
