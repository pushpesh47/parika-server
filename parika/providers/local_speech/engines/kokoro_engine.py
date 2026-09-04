"""
PARIKA Local Speech Provider - Kokoro TTS Engine Adapter

Implements `TtsEngine` against the optional `kokoro-onnx` package
(https://github.com/hexgrad/kokoro-onnx), a lightweight local
text-to-speech implementation. `kokoro-onnx` depends on `onnxruntime`
which ships Python 3.14-compatible wheels.

The `kokoro_onnx` package itself is imported lazily, inside `__init__`,
never at module import time -- following the same lazy-import convention
as the STT engine for graceful-degradation.

Kokoro TTS Language Policy (PARIKA v1):
    Hindi (`hi`) is the sole supported TTS language. All text -- Hindi,
    English, Hinglish, or mixed -- is synthesized with `lang="hi"`.
    No language selection, detection, or fallback occurs in this engine.
"""

from __future__ import annotations

import importlib.util
import re

import numpy as np

from .tts_engine import TtsEngine, TtsEngineResult


def kokoro_dependency_available() -> bool:
    """
    Whether the optional `kokoro-onnx` dependency (the `voice` extra) is
    installed.
    """

    return importlib.util.find_spec("kokoro_onnx") is not None


# Kokoro TTS uses Hindi (`hi`) as the sole language for all synthesis.
# This is not configurable: the same `hf_beta` voice with `lang="hi"`
# correctly handles Hindi, English, Hinglish, and mixed text.
KOKORO_TTS_LANG = "hi"


_ESPEAK_LANGUAGE_MARKER = re.compile(
    r"\([a-z]{2,3}(?:-[a-z0-9]{2,8})?\)"
)


def _strip_language_markers(phonemes: str) -> str:
    """Remove eSpeak language-switch annotations without touching phonemes."""

    return _ESPEAK_LANGUAGE_MARKER.sub("", phonemes)


class KokoroTtsEngine(TtsEngine):
    """
    `TtsEngine` implementation backed by the Kokoro ONNX TTS model.

    A single Kokoro model (`kokoro-v1.0.onnx`) with its voices file
    (`voices-v1.0.bin`) contains multiple voice styles. The
    `voice_name` parameter selects which style to use (default:
    "hf_beta").

    All synthesis uses `lang="hi"` regardless of input text language.
    The `language` parameter in `synthesize()` is accepted for interface
    compatibility but ignored.
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
                hardcoded.

            voice_name:
                Kokoro voice style name (e.g. "hf_beta"). Read from
                `[providers.local_speech].kokoro_voice`; never
                hardcoded.

            speed:
                Speech speed multiplier. Read from
                `[providers.local_speech].kokoro_speed`; never
                hardcoded.

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

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> TtsEngineResult:
        """
        Synthesize text to speech.

        Args:
            text: Text to synthesize.
            voice: Optional voice override (defaults to configured voice).
            language: Accepted for interface compatibility but IGNORED.
                      Kokoro always uses `lang="hi"` for all text.

        Returns:
            TtsEngineResult with PCM bytes and sample rate.
        """
        from .. import exceptions

        if not text.strip():
            raise exceptions.LocalSpeechExecutionError(
                "Cannot synthesize empty text."
            )

        kokoro_voice = voice or self._voice_name

        try:
            phonemes = _strip_language_markers(
                self._kokoro.tokenizer.phonemize(text, lang=KOKORO_TTS_LANG)
            )

            # Kokoro returns float32 numpy array, sample_rate
            # The already-phonemized text prevents Kokoro from adding
            # eSpeak language-switch annotations during synthesis.
            audio_float32, sample_rate = self._kokoro.create(
                text=phonemes,
                voice=kokoro_voice,
                speed=self._speed,
                lang=KOKORO_TTS_LANG,
                is_phonemes=True,
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
