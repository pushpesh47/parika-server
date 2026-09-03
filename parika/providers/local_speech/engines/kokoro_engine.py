"""
PARIKA Local Speech Provider - Kokoro TTS Engine Adapter

Implements `TtsEngine` against the optional `kokoro-onnx` package
(https://github.com/hexgrad/kokoro-onnx), a lightweight local
text-to-speech implementation. `kokoro-onnx` depends on `onnxruntime`
which ships Python 3.14-compatible wheels.

The `kokoro_onnx` package itself is imported lazily, inside `__init__`,
never at module import time -- following the same lazy-import convention
as the STT engine for graceful-degradation.
"""

from __future__ import annotations

import importlib.util

import numpy as np

from .tts_engine import TtsEngine, TtsEngineResult


def kokoro_dependency_available() -> bool:
    """
    Whether the optional `kokoro-onnx` dependency (the `voice` extra) is
    installed.
    """

    return importlib.util.find_spec("kokoro_onnx") is not None


# Language mapping from PARIKA language codes to Kokoro language codes.
# PARIKA's Voice Module (VoiceLanguagePreferenceStore) resolves output
# language to concrete "en" or "hi" before reaching the engine.
KOKORO_LANG_MAP = {
    "hi": "hi",
    "en": "en-us",
}


class KokoroTtsEngine(TtsEngine):
    """
    `TtsEngine` implementation backed by the Kokoro ONNX TTS model.

    A single Kokoro model (`kokoro-v1.0.onnx`) with its voices file
    (`voices-v1.0.bin`) contains multiple voice styles. The
    `voice_name` parameter selects which style to use (default:
    "hf_beta").

    `synthesize(..., language=...)` maps the language to Kokoro's
    expected language codes via `KOKORO_LANG_MAP`. An unrecognized
    language falls back to `"en-us"`.

    The engine uses CPU by default for Phase 1 (no GPU contention with
    local LLM inference). Device selection is not currently exposed
    because `kokoro-onnx` does not provide a meaningful device selection
    API.
    """

    # Kokoro ONNX uses a fixed 24 kHz sample rate.
    _SAMPLE_RATE = 24000

    def __init__(
        self,
        *,
        model_path: str,
        voices_path: str,
        voice_name: str = "hf_beta",
        speed: float = 1.0,
        language: str = "en",
    ) -> None:
        """
        Construct the engine, loading the underlying Kokoro model.

        Args:
            model_path:
                Filesystem path to the Kokoro ONNX model file
                (`kokoro-v1.0.onnx`). Read from
                `[providers.local_speech].kokoro_model_path`; never
                hardcoded here.

            voices_path:
                Filesystem path to the Kokoro voices file
                (`voices-v1.0.bin`). Read from
                `[providers.local_speech].kokoro_voices_path`; never
                hardcoded here.

            voice_name:
                Kokoro voice style name (e.g. "hf_beta"). Read from
                `[providers.local_speech].kokoro_voice`; never
                hardcoded.

            speed:
                Speech speed multiplier. Read from
                `[providers.local_speech].kokoro_speed`; never
                hardcoded.

            language:
                The default language code (e.g. "en") this engine uses
                when no explicit language is requested -- used only to
                resolve `synthesize(..., language=...)` requests; never
                sent to Kokoro directly.

        Raises:
            LocalSpeechEngineUnavailableError:
                If the optional `kokoro-onnx` dependency is not
                installed, or `model_path`/`voices_path` is empty/not
                configured.

            LocalSpeechEngineInitializationError:
                If the model could not be loaded.
        """

        from .. import exceptions

        if not kokoro_dependency_available():
            raise exceptions.LocalSpeechEngineUnavailableError(
                "Text-to-speech via Kokoro requires the optional "
                "'voice' dependency group (kokoro-onnx) to be "
                "installed."
            )

        if not model_path:
            raise exceptions.LocalSpeechEngineUnavailableError(
                "Text-to-speech via Kokoro requires "
                "[providers.local_speech].kokoro_model_path to be set "
                "to the Kokoro ONNX model file (kokoro-v1.0.onnx)."
            )

        if not voices_path:
            raise exceptions.LocalSpeechEngineUnavailableError(
                "Text-to-speech via Kokoro requires "
                "[providers.local_speech].kokoro_voices_path to be set "
                "to the Kokoro voices file (voices-v1.0.bin)."
            )

        from kokoro_onnx import Kokoro  # noqa: PLC0415

        self._voice_name = voice_name
        self._speed = speed
        self._language = language

        try:
            self._kokoro = Kokoro(model_path=model_path, voices_path=voices_path)
        except Exception as ex:  # noqa: BLE001
            raise exceptions.LocalSpeechEngineInitializationError(
                f"Could not initialize Kokoro model '{model_path}' "
                f"with voices '{voices_path}': {ex}"
            ) from ex

        # Verify the voice exists
        available_voices = self._kokoro.get_voices()
        if voice_name not in available_voices:
            raise exceptions.LocalSpeechEngineInitializationError(
                f"Kokoro voice '{voice_name}' not found in available "
                f"voices: {available_voices}"
            )

    @property
    def sample_rate(self) -> int:
        """Sample rate, in Hz, the Kokoro model synthesizes at."""

        return self._SAMPLE_RATE

    def _map_language(self, language: str | None) -> str:
        """
        Map PARIKA language code to Kokoro language code.

        Falls back to "en-us" for unrecognized/None languages.
        """

        if language is None:
            return KOKORO_LANG_MAP.get(self._language, "en-us")

        return KOKORO_LANG_MAP.get(language, "en-us")

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> TtsEngineResult:
        from .. import exceptions

        if not text.strip():
            raise exceptions.LocalSpeechExecutionError(
                "Cannot synthesize empty text."
            )

        kokoro_lang = self._map_language(language)
        kokoro_voice = voice or self._voice_name

        try:
            # Kokoro returns float32 numpy array, sample_rate
            audio_float32, sample_rate = self._kokoro.create(
                text=text,
                voice=kokoro_voice,
                speed=self._speed,
                lang=kokoro_lang,
            )

            # Convert float32 [-1.0, 1.0] to int16 little-endian PCM bytes
            # Clip to prevent overflow
            audio_clipped = np.clip(audio_float32, -1.0, 1.0)
            audio_int16 = (audio_clipped * 32767).astype(np.int16)
            pcm_bytes = audio_int16.tobytes()

        except Exception as ex:  # noqa: BLE001
            raise exceptions.LocalSpeechExecutionError(
                f"Kokoro failed to synthesize the supplied text: {ex}"
            ) from ex

        return TtsEngineResult(pcm_bytes=pcm_bytes, sample_rate=sample_rate)