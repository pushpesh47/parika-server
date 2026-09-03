"""
PARIKA Local Speech Provider - Manifest

Defines the static Provider metadata describing the Local Speech
provider.

This module owns Provider creation. `ProviderManager` only registers
and stores the `Provider` instance produced here; it does not create
`Provider` objects itself -- exactly the pattern already established
by `parika/providers/comfyui/manifest.py`/
`parika/providers/ollama/manifest.py`.
"""

from __future__ import annotations

from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.state_manager.states import ProviderState

LOCAL_SPEECH_PROVIDER_ID = "provider.local_speech"
"""
Identifier of the Provider registered with ProviderManager.
"""


def create_local_speech_provider(
    *,
    models: frozenset[ProviderModel] = frozenset(),
    state: ProviderState = ProviderState.DISCONNECTED,
    enabled: bool = True,
) -> Provider:
    """
    Build the immutable Provider descriptor for the Local Speech
    provider.

    Args:
        models:
            Models discovered so far. Typically supplied after calling
            `ProviderManager.discover_models(LOCAL_SPEECH_PROVIDER_ID)`,
            or left empty when registering before the first discovery.

        state:
            Initial connectivity state.

        enabled:
            Whether the provider is enabled for routing.

    Returns:
        A Provider ready to be registered with ProviderManager
        alongside a `LocalSpeechProviderDriver` instance.
    """

    return Provider(
        id=LOCAL_SPEECH_PROVIDER_ID,
        name="Local Speech",
        description=(
            "Local, on-device speech-to-text (faster-whisper) and "
            "text-to-speech (Kokoro) engines, running entirely on "
            "this machine -- never an LLM, never a remote service."
        ),
        state=state,
        enabled=enabled,
        models=models,
    )
