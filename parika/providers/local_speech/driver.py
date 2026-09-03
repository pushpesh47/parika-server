"""
PARIKA Local Speech Provider - Driver

Implements the `ProviderDriver` contract
(`parika.core.provider_manager.driver.ProviderDriver`) against local
STT/TTS engines, selected purely by configuration
(`[providers.local_speech].stt_engine`/`tts_engine`) -- never
hardcoded -- through the `SttEngine`/`TtsEngine` Protocols (see
`engines/__init__.py`).

This driver contains no registration, lifecycle, or capability-
routing logic; that is owned by `ProviderManager` and whatever
composition root registers this provider (see
`parika/interfaces/runtime.py`), exactly like every other Provider
driver.

Engines are constructed lazily, on first use, and cached for this
driver's lifetime: importing/registering this provider never requires
an engine's optional dependency to be installed, or its model to be
loaded into memory, until a request actually needs it -- consistent
with `discovery.py`'s "installed environment is authoritative" model
listing (which only checks *presence*, never loads).
"""

from __future__ import annotations

import base64
import time

from parika.core.logger.logger import Logger
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse
from parika.core.provider_manager.speech_request import SpeechOperation, SpeechRequest
from parika.core.provider_manager.speech_result import SpeechResult

from . import discovery
from .audio import pcm16_to_wav
from .config import LocalSpeechProviderConfig
from .engines.faster_whisper_engine import FasterWhisperSttEngine
from .engines.kokoro_engine import KokoroTtsEngine
from .engines.piper_engine import PiperTtsEngine, PiperVoiceSpec
from .engines.stt_engine import SttEngine
from .engines.tts_engine import TtsEngine
from .exceptions import LocalSpeechRequestError


class LocalSpeechProviderDriver(ProviderDriver):
    """
    ProviderDriver implementation backed by local STT/TTS engines.
    """

    def __init__(
        self,
        *,
        config: LocalSpeechProviderConfig,
        logger: Logger,
    ) -> None:
        self._config = config
        self._logger = logger.get_logger(__name__)

        self._stt_engine: SttEngine | None = None
        self._tts_engine: TtsEngine | None = None

    # ------------------------------------------------------------------
    # ProviderDriver contract
    # ------------------------------------------------------------------

    def discover_models(self) -> frozenset[ProviderModel]:
        """
        Discover which of this provider's two synthetic `ProviderModel`s
        (speech-to-text, text-to-speech) are actually usable, per
        `discovery.discover_models()`. Never loads an engine into
        memory -- only checks dependency/model-file presence.
        """

        return discovery.discover_models(config=self._config)  # type: ignore[return-value]

    def check_health(self) -> ProviderHealth:
        """
        Report whether at least one speech engine is currently usable.

        Deliberately cheap: reuses the same presence checks
        `discover_models()` performs rather than actually loading any
        engine, so a health check never pays a model-load cost.
        """

        started_at = time.perf_counter()
        models = discovery.discover_models(config=self._config)
        latency_ms = (time.perf_counter() - started_at) * 1000

        if not models:
            return ProviderHealth(
                available=False,
                latency_ms=latency_ms,
                message=(
                    "No local speech engine is currently installed/"
                    "configured (faster-whisper and/or a Piper voice "
                    "model)."
                ),
            )

        names = ", ".join(sorted(model.name for model in models))

        return ProviderHealth(
            available=True,
            latency_ms=latency_ms,
            message=f"Local speech engines available: {names}",
        )

    def execute(
        self,
        model: ProviderModel,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """
        Execute a `SpeechRequest` using the specified local speech
        model.

        Raises:
            LocalSpeechRequestError:
                If `request` is not a `SpeechRequest`, or the selected
                `model`/operation combination is unsupported.
        """

        if not isinstance(request, SpeechRequest):
            raise LocalSpeechRequestError(
                "LocalSpeechProviderDriver only supports SpeechRequest, "
                f"got {type(request).__name__!r}."
            )

        if request.operation is SpeechOperation.SPEECH_TO_TEXT:
            return self._transcribe(model, request)

        if request.operation is SpeechOperation.TEXT_TO_SPEECH:
            return self._synthesize(model, request)

        raise LocalSpeechRequestError(
            f"LocalSpeechProviderDriver does not support operation "
            f"{request.operation!r}."
        )

    # ------------------------------------------------------------------
    # Operation handlers
    # ------------------------------------------------------------------

    def _transcribe(
        self, model: ProviderModel, request: SpeechRequest
    ) -> SpeechResult:
        if not request.audio_base64:
            raise LocalSpeechRequestError(
                "speech_to_text requires SpeechRequest.audio_base64."
            )

        engine = self._get_stt_engine()
        audio_bytes = base64.b64decode(request.audio_base64)
        # "auto" (the Voice Module's explicit sentinel for automatic
        # detection -- see `parika.modules.voice.language`) is
        # equivalent to omitting a language hint entirely: both mean
        # "let the engine detect it".
        requested_language = request.language or self._config.stt_default_language
        language = None if requested_language in (None, "", "auto") else requested_language

        result = engine.transcribe(audio_bytes, language=language)

        return SpeechResult(
            model_id=model.id,
            text=result.text,
            language_detected=result.language_detected,
            duration_seconds=result.duration_seconds,
            language_confidence=result.language_probability,
        )

    def _synthesize(
        self, model: ProviderModel, request: SpeechRequest
    ) -> SpeechResult:
        if not request.text.strip():
            raise LocalSpeechRequestError(
                "text_to_speech requires a non-empty SpeechRequest.text."
            )

        engine = self._get_tts_engine()
        result = engine.synthesize(
            request.text, voice=request.voice, language=request.language
        )

        wav_bytes = pcm16_to_wav(
            result.pcm_bytes, sample_rate=result.sample_rate
        )

        return SpeechResult(
            model_id=model.id,
            audio_base64=base64.b64encode(wav_bytes).decode("ascii"),
            audio_mime_type="audio/wav",
            sample_rate=result.sample_rate,
        )

    # ------------------------------------------------------------------
    # Lazy engine construction
    # ------------------------------------------------------------------

    def _get_stt_engine(self) -> SttEngine:
        if self._stt_engine is None:
            self._logger.info(
                "Loading faster-whisper model '%s' (device=%s)...",
                self._config.stt_model_size,
                self._config.stt_device,
            )
            self._stt_engine = FasterWhisperSttEngine(
                model_size=self._config.stt_model_size,
                device=self._config.stt_device,
                compute_type=self._config.stt_compute_type,
                download_root=self._config.stt_model_directory,
                beam_size=self._config.stt_beam_size,
            )

        return self._stt_engine

    def _get_tts_engine(self) -> TtsEngine:
        if self._tts_engine is None:
            if self._config.tts_engine == "kokoro":
                self._logger.info(
                    "Loading Kokoro voice: %s (model=%s, voices=%s)...",
                    self._config.tts_kokoro_voice,
                    self._config.tts_kokoro_model_path,
                    self._config.tts_kokoro_voices_path,
                )
                self._tts_engine = KokoroTtsEngine(
                    model_path=self._config.tts_kokoro_model_path,
                    voices_path=self._config.tts_kokoro_voices_path,
                    voice_name=self._config.tts_kokoro_voice,
                    speed=self._config.tts_kokoro_speed,
                    language="en",
                )
            elif self._config.tts_engine == "piper":
                additional_voices: dict[str, PiperVoiceSpec] = {}

                if self._config.tts_hindi_model_path:
                    additional_voices["hi"] = PiperVoiceSpec(
                        model_path=self._config.tts_hindi_model_path,
                        config_path=self._config.tts_hindi_config_path or None,
                        speaker_id=self._config.tts_hindi_speaker_id,
                    )

                self._logger.info(
                    "Loading Piper voice(s): en=%s%s (device=%s)...",
                    self._config.tts_voice,
                    (
                        f", hi={self._config.tts_hindi_voice}"
                        if "hi" in additional_voices
                        else ""
                    ),
                    self._config.tts_device,
                )
                self._tts_engine = PiperTtsEngine(
                    model_path=self._config.tts_model_path,
                    config_path=self._config.tts_config_path or None,
                    device=self._config.tts_device,
                    speaker_id=self._config.tts_speaker_id,
                    length_scale=self._config.tts_length_scale,
                    noise_scale=self._config.tts_noise_scale,
                    noise_w=self._config.tts_noise_w,
                    language="en",
                    additional_voices=additional_voices or None,
                )
            else:
                raise LocalSpeechRequestError(
                    f"Unsupported tts_engine '{self._config.tts_engine}'. "
                    "Supported values: 'piper', 'kokoro'."
                )

        return self._tts_engine
