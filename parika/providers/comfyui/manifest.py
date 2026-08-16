"""
PARIKA ComfyUI Provider - Manifest

Defines the static Provider metadata describing the ComfyUI provider.

This module owns Provider creation. `ProviderManager` only registers
and stores the `Provider` instance produced here; it does not create
`Provider` objects itself -- exactly the pattern already established
by `parika/providers/ollama/manifest.py`.
"""

from __future__ import annotations

from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.state_manager.states import ProviderState

COMFYUI_PROVIDER_ID = "provider.comfyui"
"""
Identifier of the Provider registered with ProviderManager.
"""


def create_comfyui_provider(
    *,
    models: frozenset[ProviderModel] = frozenset(),
    state: ProviderState = ProviderState.DISCONNECTED,
    enabled: bool = True,
) -> Provider:
    """
    Build the immutable Provider descriptor for ComfyUI.

    Args:
        models:
            Models discovered so far. Typically supplied after calling
            `ProviderManager.discover_models(COMFYUI_PROVIDER_ID)`, or
            left empty when registering before the first discovery.

        state:
            Initial connectivity state.

        enabled:
            Whether the provider is enabled for routing.

    Returns:
        A Provider ready to be registered with ProviderManager
        alongside a `ComfyUIProviderDriver` instance.
    """

    return Provider(
        id=COMFYUI_PROVIDER_ID,
        name="ComfyUI",
        description=(
            "Local ComfyUI server providing image generation, image "
            "editing, and text/image-to-video generation through "
            "whatever diffusion models are actually installed."
        ),
        state=state,
        enabled=enabled,
        models=models,
    )
