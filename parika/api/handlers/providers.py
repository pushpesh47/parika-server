"""
PARIKA API - Providers Handler
"""

from __future__ import annotations

from typing import Any

from parika.interfaces.runtime import ParikaRuntime

from ..requests import ProvidersListRequest


def handle_providers_list(
    runtime: ParikaRuntime, request: ProvidersListRequest | None
) -> list[dict[str, Any]]:
    """
    Return every registered Provider and its discovered models,
    mirroring `/providers`.
    """

    providers = []

    for provider in sorted(runtime.provider_manager.get_all(), key=lambda item: item.id):
        health = provider.health

        providers.append(
            {
                "id": provider.id,
                "name": provider.name,
                "enabled": provider.enabled,
                "state": provider.state.value,
                "available": None if health is None else health.available,
                "models": [
                    {
                        "id": model.id,
                        "capabilities": sorted(
                            capability.value for capability in model.capabilities
                        ),
                    }
                    for model in sorted(provider.models, key=lambda item: item.id)
                ],
            }
        )

    return providers
