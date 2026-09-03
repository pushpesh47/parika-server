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

`stt_device`/`tts_device` deliberately accept the free-form string
`"auto"` (the default) alongside any concrete device string an engine
understands (e.g. `"cpu"`, `"cuda"`) -- this module and the Voice
Module never hardcode `"cuda"`/`"cpu"` themselves; `"auto"` is resolved
by each engine adapter using whatever device-detection the engine
itself provides (see `engines/faster_whisper_engine.py`'s and
`engines/piper_engine.py`'s own graceful CPU fallback).
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

DEFAULT_TTS_ENGINE = "piper"
# English Piper voice. `en_US-amy-medium` is a real, single-speaker
# Piper voice confirmed female in the upstream `rhasspy/piper-voices`
# catalog -- the closest available substitute in the absence of any
# official Indian-English (`en_IN`) Piper voice at the time this
# Module's task was implemented (Piper's official catalog covers
# `en_US`/`en_GB` only for English; see `docs/architecture/adr/
# 0002-voice-capability.md`'s language-model decision for the full
# inventory this default was chosen from, and the explicit limitation
# this records). `tts_voice` remains a human-readable label only, as
# before -- never consulted by `PiperTtsEngine` itself.
DEFAULT_TTS_VOICE = "en_US-amy-medium"
DEFAULT_TTS_MODEL_PATH = ""
DEFAULT_TTS_CONFIG_PATH = ""
DEFAULT_TTS_DEVICE = "auto"
DEFAULT_TTS_SAMPLE_RATE = 22050
DEFAULT_TTS_SPEAKER_ID: int | None = None
DEFAULT_TTS_LENGTH_SCALE = 1.0
DEFAULT_TTS_NOISE_SCALE = 0.667
DEFAULT_TTS_NOISE_W = 0.8

# Hindi Piper voice. `hi_IN-priyamvada-medium` is `rhasspy/piper-
# voices`' real, confirmed-female `hi_IN` (Hindi, India) voice -- a
# genuinely Indian, Hindi, female voice (unlike the English slot
# above, Piper's official Hindi catalog is `hi_IN`-only, so no
# substitute/limitation applies here). Configuring
# `tts_hindi_model_path` is what actually makes Hindi text-to-speech
# available; leaving it unset simply means Hindi output falls back to
# the English voice (see `PiperTtsEngine`'s own docstring) rather than
# failing.
DEFAULT_TTS_HINDI_VOICE = "hi_IN-priyamvada-medium"
DEFAULT_TTS_HINDI_MODEL_PATH = ""
DEFAULT_TTS_HINDI_CONFIG_PATH = ""
DEFAULT_TTS_HINDI_SPEAKER_ID: int | None = None

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

    TTS is deliberately configured as two independent voice "slots"
    -- English (`tts_voice`/`tts_model_path`/`tts_config_path`/
    `tts_speaker_id`, unchanged field names for backward
    compatibility) and Hindi (`tts_hindi_*`) -- rather than a single
    generic voice, per this Module's Indian-female-voice-per-language
    task requirement. `tts_length_scale`/`tts_noise_scale`/
    `tts_noise_w`/`tts_device` remain shared synthesis/placement
    tuning applied to whichever voice is actually used.
    """

    enabled: bool = DEFAULT_ENABLED

    stt_engine: str = DEFAULT_STT_ENGINE
    stt_model_size: str = DEFAULT_STT_MODEL_SIZE
    stt_device: str = DEFAULT_STT_DEVICE
    stt_compute_type: str = DEFAULT_STT_COMPUTE_TYPE
    stt_default_language: str | None = DEFAULT_STT_DEFAULT_LANGUAGE
    stt_model_directory: str | None = DEFAULT_STT_MODEL_DIRECTORY
    stt_beam_size: int = DEFAULT_STT_BEAM_SIZE

    tts_engine: str = DEFAULT_TTS_ENGINE
    tts_voice: str = DEFAULT_TTS_VOICE
    tts_model_path: str = DEFAULT_TTS_MODEL_PATH
    tts_config_path: str = DEFAULT_TTS_CONFIG_PATH
    tts_device: str = DEFAULT_TTS_DEVICE
    tts_sample_rate: int = DEFAULT_TTS_SAMPLE_RATE
    tts_speaker_id: int | None = DEFAULT_TTS_SPEAKER_ID
    tts_length_scale: float = DEFAULT_TTS_LENGTH_SCALE
    tts_noise_scale: float = DEFAULT_TTS_NOISE_SCALE
    tts_noise_w: float = DEFAULT_TTS_NOISE_W

    tts_hindi_voice: str = DEFAULT_TTS_HINDI_VOICE
    tts_hindi_model_path: str = DEFAULT_TTS_HINDI_MODEL_PATH
    tts_hindi_config_path: str = DEFAULT_TTS_HINDI_CONFIG_PATH
    tts_hindi_speaker_id: int | None = DEFAULT_TTS_HINDI_SPEAKER_ID

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
        tts_engine=str(
            configuration.get(
                "providers.local_speech.tts_engine", defaults.tts_engine
            )
        ),
        tts_voice=str(
            configuration.get(
                "providers.local_speech.tts_voice", defaults.tts_voice
            )
        ),
        tts_model_path=str(
            configuration.get(
                "providers.local_speech.tts_model_path", defaults.tts_model_path
            )
        ),
        tts_config_path=str(
            configuration.get(
                "providers.local_speech.tts_config_path",
                defaults.tts_config_path,
            )
        ),
        tts_device=str(
            configuration.get(
                "providers.local_speech.tts_device", defaults.tts_device
            )
        ),
        tts_sample_rate=int(
            configuration.get(
                "providers.local_speech.tts_sample_rate",
                defaults.tts_sample_rate,
            )
        ),
        tts_speaker_id=(
            lambda value: int(value) if value is not None else None
        )(
            configuration.get(
                "providers.local_speech.tts_speaker_id", defaults.tts_speaker_id
            )
        ),
        tts_length_scale=float(
            configuration.get(
                "providers.local_speech.tts_length_scale",
                defaults.tts_length_scale,
            )
        ),
        tts_noise_scale=float(
            configuration.get(
                "providers.local_speech.tts_noise_scale",
                defaults.tts_noise_scale,
            )
        ),
        tts_noise_w=float(
            configuration.get(
                "providers.local_speech.tts_noise_w", defaults.tts_noise_w
            )
        ),
        tts_hindi_voice=str(
            configuration.get(
                "providers.local_speech.tts_hindi_voice", defaults.tts_hindi_voice
            )
        ),
        tts_hindi_model_path=str(
            configuration.get(
                "providers.local_speech.tts_hindi_model_path",
                defaults.tts_hindi_model_path,
            )
        ),
        tts_hindi_config_path=str(
            configuration.get(
                "providers.local_speech.tts_hindi_config_path",
                defaults.tts_hindi_config_path,
            )
        ),
        tts_hindi_speaker_id=(
            lambda value: int(value) if value is not None else None
        )(
            configuration.get(
                "providers.local_speech.tts_hindi_speaker_id",
                defaults.tts_hindi_speaker_id,
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
