"""
PARIKA Ollama Provider - Manifest

Defines the static Provider metadata describing the Ollama provider.

This module owns Provider creation. `ProviderManager` only registers
and stores the `Provider` instance produced here; it does not create
`Provider` objects itself (mirroring the pattern already established
by `parika/tools/web_search/manifest.py` for Tools).
"""

from __future__ import annotations

from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.state_manager.states import ProviderState

OLLAMA_PROVIDER_ID = "provider.ollama"
"""
Identifier of the Provider registered with ProviderManager.
"""


def create_ollama_provider(
    *,
    models: frozenset[ProviderModel] = frozenset(),
    state: ProviderState = ProviderState.DISCONNECTED,
    enabled: bool = True,
) -> Provider:
    """
    Build the immutable Provider descriptor for Ollama.

    Args:
        models:
            Models discovered so far. Typically supplied after calling
            `ProviderManager.discover_models(OLLAMA_PROVIDER_ID)`, or
            left empty when registering before the first discovery.

        state:
            Initial connectivity state.

        enabled:
            Whether the provider is enabled for routing.

    Returns:
        A Provider ready to be registered with ProviderManager
        alongside an `OllamaProviderDriver` instance.
    """

    return Provider(
        id=OLLAMA_PROVIDER_ID,
        name="Ollama",
        description=(
            "Local Ollama server providing text generation, chat, "
            "and tool calling for any installed Ollama-compatible "
            "model."
        ),
        state=state,
        enabled=enabled,
        models=models,
    )
