"""
PARIKA Local Speech Provider - Piper TTS Engine Adapter

Implements `TtsEngine` against the optional `piper-tts` package
(https://github.com/OHF-Voice/piper1-gpl), PARIKA's preferred
lightweight local text-to-speech implementation, per this Module's
task-level requirement to verify compatibility first: `piper-tts`
depends on `onnxruntime<2`, and `onnxruntime>=1.24.1` ships Python
3.14-compatible wheels, so a compatible pairing exists for the pinned
Python version -- see this package's own `docs/development/` note and
`pyproject.toml`'s `voice` extra comment for the full compatibility
record, including the `piper-tts` license caveat (GPL-3.0-or-later).

The `piper` package itself is imported lazily, inside `__init__`,
never at module import time -- mirroring
`faster_whisper_engine.py`'s own lazy-import convention exactly, for
the same graceful-degradation reason.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, Mapping

from .tts_engine import TtsEngine, TtsEngineResult
from piper.config import SynthesisConfig  # noqa: PLC0415

DEVICE_AUTO = "auto"


def piper_dependency_available() -> bool:
    """
    Whether the optional `piper-tts` dependency (the `voice` extra) is
    installed.
    """

    return importlib.util.find_spec("piper") is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class PiperVoiceSpec:
    """
    Declares one *additional* (non-primary) Piper voice this engine
    can lazily load on demand, keyed by language code (e.g. `"hi"`) by
    the caller (see `additional_voices` below).
    """

    model_path: str
    config_path: str | None = None
    speaker_id: int | None = None


class PiperTtsEngine(TtsEngine):
    """
    `TtsEngine` implementation backed by one or more local Piper voice
    models.

    Exactly one voice -- the "primary" voice (`model_path`, etc.) --
    is loaded eagerly at construction, exactly as before this Module's
    Indian-female-voice-per-language enhancement (backward compatible
    with every existing caller that never mentions `language`).
    `additional_voices` optionally declares further voices (e.g. a
    Hindi voice alongside an English primary voice), each lazily
    loaded only the first time `synthesize(..., language=...)`
    actually requests it -- consistent with this package's "never pay
    a model-load cost until a request actually needs it" convention.

    `synthesize(..., language=...)` selects which loaded voice speaks:
    an unrecognized/unconfigured `language` (including `None`) falls
    back to the primary voice -- this engine never fabricates support
    for a language it has no configured model for; see
    `LocalSpeechProviderDriver._get_tts_engine()` for how the two
    voice "slots" (`tts_model_path`/`tts_hindi_model_path`) become
    `model_path`/`additional_voices`.
    """

    def __init__(
        self,
        *,
        model_path: str,
        config_path: str | None = None,
        device: str = DEVICE_AUTO,
        speaker_id: int | None = None,
        length_scale: float = 1.0,
        noise_scale: float = 0.667,
        noise_w: float = 0.8,
        language: str = "en",
        additional_voices: Mapping[str, PiperVoiceSpec] | None = None,
    ) -> None:
        """
        Construct the engine, loading the underlying primary Piper
        voice model.

        Args:
            model_path:
                Filesystem path to a Piper `.onnx` voice model.
                Read from
                `[providers.local_speech].tts_model_path`; never
                hardcoded here.

            config_path:
                Optional path to the voice's `.json` config file.
                `None` lets Piper look for the conventional
                `<model_path>.json` sibling file.

            device:
                `"auto"` (the default), `"cpu"`, or `"cuda"`. `"auto"`
                first attempts CUDA, then gracefully falls back to CPU
                if that fails (no GPU/driver, or no `onnxruntime-gpu`
                installed) -- an explicit, non-`"auto"` device that
                fails to initialize is *not* silently overridden; see
                `LocalSpeechEngineInitializationError`. Also used for
                any `additional_voices` loaded later.

            speaker_id:
                Optional speaker id, for multi-speaker voice models.

            length_scale / noise_scale / noise_w:
                Piper synthesis tuning parameters (speech rate and
                variability). Read from configuration; never
                hardcoded. Shared across the primary voice and any
                `additional_voices`.

            language:
                The language code (e.g. `"en"`) this primary voice
                speaks -- used only to resolve `synthesize(...,
                language=...)` requests against `additional_voices`;
                never sent to Piper itself.

            additional_voices:
                Optional mapping of language code (e.g. `"hi"`) to
                `PiperVoiceSpec`, each lazily loaded on first use.

        Raises:
            LocalSpeechEngineUnavailableError:
                If the optional `piper-tts` dependency is not
                installed, or `model_path` is empty/not configured.

            LocalSpeechEngineInitializationError:
                If the voice model could not be loaded.
        """

        from .. import exceptions

        if not piper_dependency_available():
            raise exceptions.LocalSpeechEngineUnavailableError(
                "Text-to-speech via Piper requires the optional "
                "'voice' dependency group (piper-tts) to be "
                "installed."
            )

        if not model_path:
            raise exceptions.LocalSpeechEngineUnavailableError(
                "Text-to-speech via Piper requires "
                "[providers.local_speech].tts_model_path to be set "
                "to an installed Piper voice model (.onnx) file."
            )

        from piper import PiperVoice  # noqa: PLC0415

        self._speaker_id = speaker_id
        self._length_scale = length_scale
        self._noise_scale = noise_scale
        self._noise_w = noise_w
        self._device = device
        self._language = language

        self._voice = self._load_voice(
            PiperVoice,
            model_path=model_path,
            config_path=config_path,
            device=device,
        )
        self._sample_rate = int(self._voice.config.sample_rate)

        self._additional_voice_specs: dict[str, PiperVoiceSpec] = dict(
            additional_voices or {}
        )
        self._loaded_additional_voices: dict[str, Any] = {}
        self._additional_sample_rates: dict[str, int] = {}

    def _load_voice(
        self,
        piper_voice_cls,
        *,
        model_path: str,
        config_path: str | None,
        device: str,
    ):
        from .. import exceptions

        candidate_use_cuda = (True, False) if device == DEVICE_AUTO else (
            (device == "cuda",)
        )
        last_error: Exception | None = None

        for use_cuda in candidate_use_cuda:
            try:
                return piper_voice_cls.load(
                    model_path,
                    config_path=config_path or None,
                    use_cuda=use_cuda,
                )

            except Exception as ex:  # noqa: BLE001
                last_error = ex

                if device != DEVICE_AUTO:
                    break

        raise exceptions.LocalSpeechEngineInitializationError(
            f"Could not initialize Piper voice model '{model_path}' "
            f"(device={device!r}): {last_error}"
        ) from last_error

    @property
    def sample_rate(self) -> int:
        """Sample rate, in Hz, the primary voice model synthesizes at."""

        return self._sample_rate

    def _get_additional_voice(self, language: str) -> tuple[Any, int]:
        """
        Lazily load (once) and return the `(voice, sample_rate)` for
        one `additional_voices` entry.
        """

        if language not in self._loaded_additional_voices:
            spec = self._additional_voice_specs[language]

            from piper import PiperVoice  # noqa: PLC0415

            voice = self._load_voice(
                PiperVoice,
                model_path=spec.model_path,
                config_path=spec.config_path,
                device=self._device,
            )
            self._loaded_additional_voices[language] = voice
            self._additional_sample_rates[language] = int(voice.config.sample_rate)

        return (
            self._loaded_additional_voices[language],
            self._additional_sample_rates[language],
        )

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

        if language and language != self._language and language in self._additional_voice_specs:
            target_voice, sample_rate = self._get_additional_voice(language)
            speaker_id = self._additional_voice_specs[language].speaker_id
        else:
            # Unrecognized/unconfigured/omitted language -> the
            # primary voice. Never fabricates support for a language
            # this engine has no configured model for.
            target_voice = self._voice
            sample_rate = self._sample_rate
            speaker_id = self._speaker_id

        try:
            synthesis_config = SynthesisConfig(
                speaker_id=speaker_id,
                length_scale=self._length_scale,
                noise_scale=self._noise_scale,
                noise_w_scale=self._noise_w,
                normalize_audio=False,
            )

            pcm_bytes = b"".join(
                chunk.audio_int16_bytes
                for chunk in target_voice.synthesize(
                    text,
                    syn_config=synthesis_config,
                )
            )

        except Exception as ex:  # noqa: BLE001
            raise exceptions.LocalSpeechExecutionError(
                f"Piper failed to synthesize the supplied text: {ex}"
            ) from ex

        return TtsEngineResult(pcm_bytes=pcm_bytes, sample_rate=sample_rate)
