"""
PARIKA Local Speech Provider - faster-whisper STT Engine Adapter

Implements `SttEngine` against the optional `faster-whisper` package
(https://github.com/SYSTRAN/faster-whisper), PARIKA's preferred local
speech-to-text implementation (see `docs/architecture/adr/` for the
compatibility investigation this Module's task recorded: `faster-
whisper>=1.3` ships Python 3.14-compatible wheels for its
`ctranslate2`/`av`/`onnxruntime` dependencies).

The `faster_whisper` package itself is imported lazily, inside
`__init__`, never at module import time -- so importing this module
(e.g. transitively, through `parika.providers.local_speech`) never
requires the optional dependency to be installed; only actually
constructing `FasterWhisperSttEngine` does. This mirrors
`parika.modules.vision.config`'s `importlib.util.find_spec()`-based
graceful-degradation pattern.

Whisper models are inherently multilingual (the same model checkpoint
recognizes ~99 languages, including English and Hindi, with no
separate per-language model to configure) -- `language` is passed
through as a recognition *hint*; omitting it lets the model
auto-detect.
"""

from __future__ import annotations

import importlib.util
import io

from .stt_engine import SttEngine, SttEngineResult

DEVICE_AUTO = "auto"


def faster_whisper_dependency_available() -> bool:
    """
    Whether the optional `faster-whisper` dependency (the `voice`
    extra) is installed.
    """

    return importlib.util.find_spec("faster_whisper") is not None


class FasterWhisperSttEngine(SttEngine):
    """
    `SttEngine` implementation backed by a local `faster-whisper`
    `WhisperModel`.
    """

    def __init__(
        self,
        *,
        model_size: str,
        device: str = DEVICE_AUTO,
        compute_type: str = "default",
        download_root: str | None = None,
        beam_size: int = 5,
    ) -> None:
        """
        Construct the engine, loading the underlying model.

        Args:
            model_size:
                A faster-whisper model size/id (e.g. `"tiny"`,
                `"base"`, `"small"`, `"medium"`, `"large-v3"`) or a
                local path to a converted CTranslate2 model directory.
                Read from `[providers.local_speech].stt_model_size`;
                never hardcoded here.

            device:
                `"auto"` (the default), `"cpu"`, or any device string
                the underlying `ctranslate2` runtime accepts (e.g.
                `"cuda"`). `"auto"` first attempts `"cuda"`, then
                gracefully falls back to `"cpu"` if that fails (no
                GPU/driver available) -- an explicit, non-`"auto"`
                device that fails to initialize is *not* silently
                overridden; see `LocalSpeechEngineInitializationError`.

            compute_type:
                A `ctranslate2` compute type (e.g. `"default"`,
                `"int8"`, `"float16"`, `"float32"`). `"default"` lets
                `ctranslate2` choose based on the resolved device.

            download_root:
                Optional local directory to cache/read model files
                from. `None` lets `faster-whisper` use its own default
                cache location.

            beam_size:
                Beam search width used by `transcribe()`.

        Raises:
            LocalSpeechEngineUnavailableError:
                If the optional `faster-whisper` dependency is not
                installed.

            LocalSpeechEngineInitializationError:
                If the model could not be loaded (e.g. an explicit,
                non-`"auto"` device is unavailable, or the model
                file/id is invalid).
        """

        from .. import exceptions

        if not faster_whisper_dependency_available():
            raise exceptions.LocalSpeechEngineUnavailableError(
                "Speech-to-text via faster-whisper requires the "
                "optional 'voice' dependency group (faster-whisper) "
                "to be installed."
            )

        from faster_whisper import WhisperModel  # noqa: PLC0415

        self._beam_size = beam_size
        self._model_size = model_size
        self._model = self._load_model(
            WhisperModel,
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )

    def _load_model(
        self,
        whisper_model_cls,
        *,
        model_size: str,
        device: str,
        compute_type: str,
        download_root: str | None,
    ):
        from .. import exceptions

        candidate_devices = (
            ("cuda", "cpu") if device == DEVICE_AUTO else (device,)
        )
        last_error: Exception | None = None

        for candidate_device in candidate_devices:
            try:
                return whisper_model_cls(
                    model_size,
                    device=candidate_device,
                    compute_type=compute_type,
                    download_root=download_root,
                )

            except Exception as ex:  # noqa: BLE001
                last_error = ex

                if device != DEVICE_AUTO:
                    break

        raise exceptions.LocalSpeechEngineInitializationError(
            f"Could not initialize faster-whisper model '{model_size}' "
            f"(device={device!r}, compute_type={compute_type!r}): "
            f"{last_error}"
        ) from last_error

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
    ) -> SttEngineResult:
        from .. import exceptions

        if not audio_bytes:
            raise exceptions.LocalSpeechExecutionError(
                "Cannot transcribe empty audio."
            )

        if language and language != "en" and self._model_size.endswith(".en"):
            raise exceptions.LocalSpeechRequestError(
                f"Configured faster-whisper model '{self._model_size}' is "
                "English-only; recognizing language "
                f"'{language}' (e.g. Hindi) requires a multilingual "
                "model -- remove the '.en' suffix from "
                "[providers.local_speech].stt_model_size."
            )

        try:
            segments, info = self._model.transcribe(
                io.BytesIO(audio_bytes),
                language=language,
                beam_size=self._beam_size,
            )

            text = "".join(segment.text for segment in segments).strip()

        except Exception as ex:  # noqa: BLE001
            raise exceptions.LocalSpeechExecutionError(
                f"faster-whisper failed to transcribe the supplied "
                f"audio: {ex}"
            ) from ex

        language_probability = getattr(info, "language_probability", None)

        return SttEngineResult(
            text=text,
            language_detected=getattr(info, "language", None) or language,
            duration_seconds=getattr(info, "duration", None),
            language_probability=(
                float(language_probability)
                if language_probability is not None
                else None
            ),
        )
