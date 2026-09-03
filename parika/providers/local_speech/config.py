"""
PARIKA Local Speech Provider - Configuration

Reads the `[providers.local_speech]` configuration section: which
underlying STT/TTS engine to use, model selection, device/compute
placement, and synthesis tuning -- all configuration-driven, so the
engine implementation can be replaced (e.g. a future STT/TTS engine)
without any code change to the Voice Module, the Voice API, or PARIKA
Core; only this section's values change.

Mirrors `parika.providers.comfyui.model_config`'s "every field is
configuration-driven, with a dataclass default matching
`config/defaults.toml`" pattern exactly, minimized to what a local
speech provider actually needs.

`stt_device` deliberately accepts the free-form string
`"auto"` (the default) alongside any concrete device string an engine
understands (e.g. `"cpu"`, `"cuda"`) -- this module and the Voice
Module never hardcode `"cuda"`/`"cpu"` themselves; `"auto"` is resolved
by each engine adapter using whatever device-detection the engine
itself provides.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

DEFAULT_ENABLED = True

DEFAULT_STT_ENGINE = "faster_whisper"
DEFAULT_STT_MODEL_SIZE = "small"
DEFAULT_STT_DEVICE = "auto"
DEFAULT_STT_COMPUTE_TYPE = "default"
DEFAULT_STT_DEFAULT_LANGUAGE: str | None = None
DEFAULT_STT_MODEL_DIRECTORY: str | None = None
DEFAULT_STT_BEAM_SIZE = 5

# Kokoro TTS engine. `hf_beta` is a real voice style available in the
# upstream `voices-v1.0.bin` file. Kokoro uses a single ONNX model
# (`kokoro-v1.0.onnx`) with all voice styles embedded in the voices
# file. Language mapping: `hi` -> `hi`, `en`/`en-us` -> `en-us`.
# CPU-first for Phase 1 (no GPU contention with local LLM inference).
DEFAULT_TTS_KOKORO_VOICE = "hf_beta"
DEFAULT_TTS_KOKORO_MODEL_PATH = ""
DEFAULT_TTS_KOKORO_VOICES_PATH = ""
DEFAULT_TTS_KOKORO_SPEED = 1.0


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalSpeechProviderConfig:
    """
    Immutable, typed snapshot of `[providers.local_speech]`
    configuration.

    TTS is configured for Kokoro only, using a single ONNX model with
    multiple voice styles embedded in the voices file.
    """

    enabled: bool = DEFAULT_ENABLED

    stt_engine: str = DEFAULT_STT_ENGINE
    stt_model_size: str = DEFAULT_STT_MODEL_SIZE
    stt_device: str = DEFAULT_STT_DEVICE
    stt_compute_type: str = DEFAULT_STT_COMPUTE_TYPE
    stt_default_language: str | None = DEFAULT_STT_DEFAULT_LANGUAGE
    stt_model_directory: str | None = DEFAULT_STT_MODEL_DIRECTORY
    stt_beam_size: int = DEFAULT_STT_BEAM_SIZE

    tts_kokoro_voice: str = DEFAULT_TTS_KOKORO_VOICE
    tts_kokoro_model_path: str = DEFAULT_TTS_KOKORO_MODEL_PATH
    tts_kokoro_voices_path: str = DEFAULT_TTS_KOKORO_VOICES_PATH
    tts_kokoro_speed: float = DEFAULT_TTS_KOKORO_SPEED


def load_local_speech_config(
    configuration: Configuration | None,
) -> LocalSpeechProviderConfig:
    """
    Build a `LocalSpeechProviderConfig` snapshot from `Configuration`.
    """

    if configuration is None:
        return LocalSpeechProviderConfig()

    defaults = LocalSpeechProviderConfig()

    return LocalSpeechProviderConfig(
        enabled=bool(
            configuration.get("providers.local_speech.enabled", defaults.enabled)
        ),
        stt_engine=str(
            configuration.get(
                "providers.local_speech.stt_engine", defaults.stt_engine
            )
        ),
        stt_model_size=str(
            configuration.get(
                "providers.local_speech.stt_model_size", defaults.stt_model_size
            )
        ),
        stt_device=str(
            configuration.get(
                "providers.local_speech.stt_device", defaults.stt_device
            )
        ),
        stt_compute_type=str(
            configuration.get(
                "providers.local_speech.stt_compute_type",
                defaults.stt_compute_type,
            )
        ),
        stt_default_language=(
            lambda value: str(value) if value else None
        )(
            configuration.get(
                "providers.local_speech.stt_default_language",
                defaults.stt_default_language,
            )
        ),
        stt_model_directory=(
            lambda value: str(value) if value else None
        )(
            configuration.get(
                "providers.local_speech.stt_model_directory",
                defaults.stt_model_directory,
            )
        ),
        stt_beam_size=int(
            configuration.get(
                "providers.local_speech.stt_beam_size", defaults.stt_beam_size
            )
        ),
        tts_kokoro_voice=str(
            configuration.get(
                "providers.local_speech.tts_kokoro_voice", defaults.tts_kokoro_voice
            )
        ),
        tts_kokoro_model_path=str(
            configuration.get(
                "providers.local_speech.tts_kokoro_model_path",
                defaults.tts_kokoro_model_path,
            )
        ),
        tts_kokoro_voices_path=str(
            configuration.get(
                "providers.local_speech.tts_kokoro_voices_path",
                defaults.tts_kokoro_voices_path,
            )
        ),
        tts_kokoro_speed=float(
            configuration.get(
                "providers.local_speech.tts_kokoro_speed",
                defaults.tts_kokoro_speed,
            )
        ),
    )