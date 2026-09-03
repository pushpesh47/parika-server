"""
PARIKA Local Speech Provider Exceptions

Defines the exception hierarchy used by the Local Speech provider
driver and its underlying STT/TTS engine adapters.

Every exception raised by this package derives from
`LocalSpeechProviderError`. Where an equivalent, more general
`ProviderError` subtype already exists on `ProviderManager`'s public
exception vocabulary (see `parika.core.provider_manager.exceptions`),
the corresponding Local Speech exception also derives from it so that
callers written against the generic Provider contract keep working
unmodified -- exactly the dual-inheritance convention established by
`parika.providers.comfyui.exceptions`/`parika.providers.ollama.exceptions`.
"""

from __future__ import annotations

from parika.core.provider_manager.exceptions import (
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderExecutionError,
)


class LocalSpeechProviderError(Exception):
    """
    Base exception for all Local Speech provider errors.
    """


class LocalSpeechEngineUnavailableError(
    LocalSpeechProviderError, ProviderConfigurationError
):
    """
    Raised when the configured STT/TTS engine's optional Python
    dependency (e.g. `faster-whisper`, `kokoro-onnx`) is not installed,
    or when its configured model file is not present on disk.

    Never a crash on its own -- the composition root
    (`parika/interfaces/runtime.py`) catches this during best-effort
    model discovery, exactly like a missing/offline ComfyUI or Ollama
    installation, so PARIKA remains usable with Voice's Capabilities
    simply unavailable until the engine is installed/configured.
    """


class LocalSpeechEngineInitializationError(
    LocalSpeechProviderError, ProviderConfigurationError
):
    """
    Raised when a configured engine's optional dependency is
    installed but the engine itself failed to initialize (e.g. an
    unsupported `device`/`compute_type` combination, or a corrupt
    model file).
    """


class LocalSpeechRequestError(LocalSpeechProviderError, ProviderCapabilityError):
    """
    Raised when an unsupported or invalid request is supplied to the
    Local Speech provider driver (e.g. a request type other than
    `SpeechRequest`, or an operation this provider/model combination
    cannot perform).
    """


class LocalSpeechExecutionError(LocalSpeechProviderError, ProviderExecutionError):
    """
    Raised when the underlying engine fails while actually performing
    speech recognition/synthesis (e.g. malformed input audio, or an
    internal engine failure).
    """
