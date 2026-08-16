"""
Unit tests for the Ollama provider manifest factory.
"""

from __future__ import annotations

from parika.core.state_manager.states import ProviderState
from parika.providers.ollama.manifest import (
    OLLAMA_PROVIDER_ID,
    create_ollama_provider,
)


class TestCreateOllamaProvider:
    def test_default_provider_shape(self) -> None:
        provider = create_ollama_provider()

        assert provider.id == OLLAMA_PROVIDER_ID
        assert provider.name == "Ollama"
        assert provider.enabled is True
        assert provider.state is ProviderState.DISCONNECTED
        assert provider.models == frozenset()

    def test_custom_state_and_enabled(self) -> None:
        provider = create_ollama_provider(
            state=ProviderState.CONNECTED,
            enabled=False,
        )

        assert provider.state is ProviderState.CONNECTED
        assert provider.enabled is False
