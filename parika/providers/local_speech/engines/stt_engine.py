"""
PARIKA Local Speech Provider - STT Engine Protocol

Defines the small, provider-internal contract every concrete
speech-to-text engine adapter (e.g. `faster_whisper_engine.py`) must
implement. `LocalSpeechProviderDriver` depends only on this Protocol,
never on a concrete engine package -- see this package's `__init__.py`
docstring for the full rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True, kw_only=True)
class SttEngineResult:
    """
    Normalized outcome of one speech-to-text engine call.

    Attributes:
        text:
            Recognized text.

        language_detected:
            The language the engine recognized/used (e.g. `"en"`,
            `"hi"`), when it reports one.

        duration_seconds:
            Duration of the input audio, when the engine reports one.

        language_probability:
            The engine's own confidence (0.0-1.0) in
            `language_detected`, when it reports one -- e.g.
            faster-whisper's `info.language_probability`, populated
            only in automatic-language-detection mode (a caller-forced
            `language` skips the engine's own detection pass, so no
            probability exists to report). `None`, never a fabricated
            value, whenever the underlying engine does not provide
            this.
    """

    text: str
    language_detected: str | None = None
    duration_seconds: float | None = None
    language_probability: float | None = None


@runtime_checkable
class SttEngine(Protocol):
    """
    Protocol implemented by every speech-to-text engine adapter usable
    by the Local Speech provider driver.
    """

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        language: str | None = None,
    ) -> SttEngineResult:
        """
        Transcribe `audio_bytes` (raw audio file bytes, in whatever
        container/encoding the engine accepts) into text.

        Args:
            audio_bytes:
                Raw input audio file bytes.

            language:
                Optional language hint (e.g. `"en"`, `"hi"`). `None`
                lets the engine auto-detect.

        Returns:
            The normalized transcription outcome.

        Raises:
            LocalSpeechExecutionError:
                If the engine fails to transcribe the supplied audio
                (e.g. malformed/empty audio, or an internal engine
                failure).
        """
        ...
