"""
PARIKA Local Speech Provider - Model Discovery

Determines which of this provider's two declared synthetic
`ProviderModel`s (one for speech-to-text, one for text-to-speech) are
actually usable right now, following exactly the same "installed
environment is authoritative" rule
`parika.providers.comfyui.discovery` already establishes: a model is
only ever offered when its underlying dependency/model file is
actually present, so Model Selection never proposes a model this
provider cannot actually run.

Speech-to-text and text-to-speech are offered as two independent
`ProviderModel`s (rather than one model declaring both capabilities)
specifically so that either direction can be independently available/
unavailable -- e.g. `faster-whisper` installed but no Piper voice
model configured yet still offers `voice.speech_to_text` -- mirroring
Section 18's requirement to handle "STT model unavailable"/"TTS model
unavailable" as independent failure modes.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider_model import ProviderModel

from .config import LocalSpeechProviderConfig
from .engines.faster_whisper_engine import faster_whisper_dependency_available
from .engines.kokoro_engine import kokoro_dependency_available
from .engines.piper_engine import piper_dependency_available

STT_MODEL_ID = "local_speech_stt"
TTS_MODEL_ID = "local_speech_tts"


def _tts_model_installed(config: LocalSpeechProviderConfig) -> bool:
    """
    Whether at least one TTS engine is actually configured and present
    on disk -- text-to-speech becomes available as soon as either
    engine has a real model file, exactly like STT/TTS being
    independently available from each other (see this module's own
    docstring).
    """

    if config.tts_engine == "piper":
        return _piper_tts_model_installed(config)
    elif config.tts_engine == "kokoro":
        return _kokoro_tts_model_installed(config)

    return False


def _piper_tts_model_installed(config: LocalSpeechProviderConfig) -> bool:
    """
    Whether at least one of the two independent Piper voice "slots"
    (English `tts_model_path`, Hindi `tts_hindi_model_path`) is
    actually configured and present on disk.
    """

    return _english_tts_model_installed(config) or _hindi_tts_model_installed(
        config
    )


def _english_tts_model_installed(config: LocalSpeechProviderConfig) -> bool:
    if not config.tts_model_path:
        return False

    return Path(config.tts_model_path).is_file()


def _hindi_tts_model_installed(config: LocalSpeechProviderConfig) -> bool:
    if not config.tts_hindi_model_path:
        return False

    return Path(config.tts_hindi_model_path).is_file()


def _kokoro_tts_model_installed(config: LocalSpeechProviderConfig) -> bool:
    """
    Whether the Kokoro model and voices files are configured and present
    on disk.
    """

    if not config.tts_kokoro_model_path or not config.tts_kokoro_voices_path:
        return False

    return Path(config.tts_kokoro_model_path).is_file() and Path(
        config.tts_kokoro_voices_path
    ).is_file()


def discover_models(
    *,
    config: LocalSpeechProviderConfig,
) -> tuple[ProviderModel, ...]:
    """
    Build the set of usable `ProviderModel`s given this provider's
    configuration and which optional engine dependencies/model files
    are actually present.

    Returns a plain tuple, not a `frozenset`, exactly like
    `parika.providers.comfyui.discovery.discover_models()` -- see that
    function's own docstring for why (`ProviderModel.metadata` is an
    unhashable `MappingProxyType`, even though it is empty here).

    Args:
        config:
            This provider's configured engine selection/model paths.

    Returns:
        `(stt_model,)`, `(tts_model,)`, `(stt_model, tts_model)`, or
        `()`, depending on which engines are actually installed.
    """

    models: list[ProviderModel] = []

    if config.stt_engine == "faster_whisper" and faster_whisper_dependency_available():
        models.append(
            ProviderModel(
                id=STT_MODEL_ID,
                name=f"faster-whisper ({config.stt_model_size})",
                description=(
                    "Local faster-whisper speech-to-text model. "
                    "Multilingual; supports English, Hindi, and every "
                    "other language the selected model checkpoint "
                    "recognizes."
                ),
                capabilities=frozenset({ModelCapability.SPEECH_TO_TEXT}),
                specializations=frozenset({"speech_to_text"}),
                supported_modalities=frozenset({"audio"}),
            )
        )

    if config.tts_engine == "piper" and piper_dependency_available() and _tts_model_installed(
        config
    ):
        configured_voices = []

        if _english_tts_model_installed(config):
            configured_voices.append(f"en: {config.tts_voice}")

        if _hindi_tts_model_installed(config):
            configured_voices.append(f"hi: {config.tts_hindi_voice}")

        models.append(
            ProviderModel(
                id=TTS_MODEL_ID,
                name=f"Piper ({', '.join(configured_voices)})",
                description=(
                    "Local Piper text-to-speech voice model(s), one "
                    "per configured language (English/Hindi)."
                ),
                capabilities=frozenset({ModelCapability.TEXT_TO_SPEECH}),
                specializations=frozenset({"text_to_speech"}),
                supported_modalities=frozenset({"audio"}),
            )
        )

    if config.tts_engine == "kokoro" and kokoro_dependency_available() and _tts_model_installed(
        config
    ):
        models.append(
            ProviderModel(
                id=TTS_MODEL_ID,
                name=f"Kokoro ({config.tts_kokoro_voice})",
                description=(
                    "Local Kokoro text-to-speech model with multiple "
                    "voice styles. Supports English (en-us) and Hindi (hi)."
                ),
                capabilities=frozenset({ModelCapability.TEXT_TO_SPEECH}),
                specializations=frozenset({"text_to_speech"}),
                supported_modalities=frozenset({"audio"}),
            )
        )

    return tuple(models)
