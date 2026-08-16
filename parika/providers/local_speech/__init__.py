"""
PARIKA Local Speech Provider

Implements local, on-device speech-to-text and text-to-speech as a
normal PARIKA `ProviderDriver`, satisfying `voice.provider_speech_to_text`
and `voice.provider_text_to_speech` (see `parika.modules.voice`) using
whichever local engines are installed/configured -- never an LLM,
never a remote service.

See `driver.py`'s module docstring for the full architecture, and
`engines/__init__.py`'s module docstring for why the concrete STT/TTS
implementation (faster-whisper, Piper) is fully isolated behind small
Protocols.
"""

from __future__ import annotations

from .config import LocalSpeechProviderConfig, load_local_speech_config
from .driver import LocalSpeechProviderDriver
from .exceptions import (
    LocalSpeechEngineInitializationError,
    LocalSpeechEngineUnavailableError,
    LocalSpeechExecutionError,
    LocalSpeechProviderError,
    LocalSpeechRequestError,
)
from .manifest import LOCAL_SPEECH_PROVIDER_ID, create_local_speech_provider

__all__ = [
    "LOCAL_SPEECH_PROVIDER_ID",
    "LocalSpeechEngineInitializationError",
    "LocalSpeechEngineUnavailableError",
    "LocalSpeechExecutionError",
    "LocalSpeechProviderConfig",
    "LocalSpeechProviderDriver",
    "LocalSpeechProviderError",
    "LocalSpeechRequestError",
    "create_local_speech_provider",
    "load_local_speech_config",
]
