"""
PARIKA API - Modules Handler
"""

from __future__ import annotations

from typing import Any

from parika.interfaces.runtime import ParikaRuntime

from ..requests import ModulesListRequest, ModuleStartRequest, ModuleStopRequest


def handle_modules_list(
    runtime: ParikaRuntime, request: ModulesListRequest | None
) -> list[dict[str, Any]]:
    """
    Return every registered Module, mirroring `/modules`.
    """

    return [
        {
            "id": module.id,
            "version": module.manifest.version,
            "state": module.state.value,
        }
        for module in sorted(runtime.module_manager.get_all(), key=lambda item: item.id)
    ]


def handle_module_start(runtime: ParikaRuntime, request: ModuleStartRequest) -> dict[str, Any]:
    """
    Start (load) a registered Module. Delegates entirely to the
    existing `ModuleManager.load()` -- raises `ModuleNotFoundError`/
    `ModuleAlreadyLoadedError`/`ModuleLoadError` unchanged, mapped to
    HTTP by the centralized error handler (`parika/api/errors.py`).
    """

    runtime.module_manager.load(request.module_id)
    module = runtime.module_manager.get(request.module_id)

    return {"module_id": module.id, "state": module.state.value}


def handle_module_stop(runtime: ParikaRuntime, request: ModuleStopRequest) -> dict[str, Any]:
    """
    Stop (unload) an active Module. Delegates entirely to the existing
    `ModuleManager.unload()`.
    """

    runtime.module_manager.unload(request.module_id)
    module = runtime.module_manager.get(request.module_id)

    return {"module_id": module.id, "state": module.state.value}
