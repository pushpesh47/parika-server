"""
PARIKA Voice Module - Configuration

Reads the `[voice]` configuration section: whether the Module is
enabled, how the `text_to_speech` Tool chunks a long response into
bounded pieces before synthesizing each one (see
`text_chunking.py`) -- the mechanism that makes "Stop Speaking"
observable mid-response rather than only after an entire response has
already finished synthesizing -- and the *initial* Voice language
preference (`input_language`; see `language.py`); TTS is invariant Hindi.
that seeds `VoiceLanguagePreferenceStore` at startup.

Mirrors `parika.modules.generation.config`'s pattern exactly,
minimized to what this Module actually needs. STT/TTS engine
selection, model paths, device placement, and synthesis tuning
(all live in the Local Speech Provider's own configuration
(`parika.providers.local_speech.config`), not here -- this Module
never hardcodes, or even knows, which engine backs its Provider
Capabilities. Keeping language *preference* here and language *engine
configuration* there avoids duplicating any configuration value
between the two sections.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

from .language import (
    VoiceInputLanguage,
    parse_input_language,
)

DEFAULT_ENABLED = True
DEFAULT_TTS_CHUNK_MAX_CHARACTERS = 280
DEFAULT_INPUT_LANGUAGE = VoiceInputLanguage.AUTO


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceToolConfig:
    """
    Immutable, typed snapshot of `[voice]` configuration.

    Attributes:
        enabled:
            Whether this Module registers its Capabilities/Tools at
            all.

        tts_chunk_max_characters:
            Maximum characters per text-to-speech synthesis chunk (see
            `text_chunking.split_into_speech_chunks()`). Smaller
            values make a `speak` operation's cancellation more
            responsive (each chunk is a checkpoint), at the cost of
            more, smaller synthesis calls.

        input_language:
            The initial Voice input-language preference
            (`auto`/`en`/`hi`), seeding
            `VoiceLanguagePreferenceStore` at startup. Callers may
            change the *current* preference afterwards through the
            Voice API's settings endpoint without touching
            configuration.

    """

    enabled: bool = DEFAULT_ENABLED
    tts_chunk_max_characters: int = DEFAULT_TTS_CHUNK_MAX_CHARACTERS
    input_language: VoiceInputLanguage = DEFAULT_INPUT_LANGUAGE


def load_voice_config(configuration: Configuration | None) -> VoiceToolConfig:
    """
    Build a `VoiceToolConfig` snapshot from `Configuration`.
    """

    if configuration is None:
        return VoiceToolConfig()

    return VoiceToolConfig(
        enabled=bool(configuration.get("voice.enabled", DEFAULT_ENABLED)),
        tts_chunk_max_characters=int(
            configuration.get(
                "voice.tts_chunk_max_characters",
                DEFAULT_TTS_CHUNK_MAX_CHARACTERS,
            )
        ),
        input_language=parse_input_language(
            str(configuration.get("voice.input_language", DEFAULT_INPUT_LANGUAGE.value))
        ),
    )
