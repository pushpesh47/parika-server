"""
PARIKA Local Speech Provider - TTS Engine Protocol

Defines the small, provider-internal contract every concrete
text-to-speech engine adapter (e.g. `piper_engine.py`) must implement.
`LocalSpeechProviderDriver` depends only on this Protocol, never on a
concrete engine package -- see this package's `__init__.py` docstring
for the full rationale.

`synthesize()` is deliberately chunk-oriented (one call per bounded
piece of text, returning one bounded piece of raw PCM audio) rather
than whole-response-at-once: the Voice Module's `TextToSpeechToolDriver`
splits a full response into small text chunks (see
`parika.modules.voice.text_chunking`) and calls `synthesize()` once per
chunk, checking a cooperative cancellation flag between calls -- this
is what makes "Stop Speaking" a real, observable mid-synthesis
cancellation (see `parika.modules.voice.operation_registry`) rather
than a no-op that only takes effect after the entire response has
already been synthesized.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True, kw_only=True)
class TtsEngineResult:
    """
    Normalized outcome of one text-to-speech engine call.

    Attributes:
        pcm_bytes:
            Raw, 16-bit signed little-endian, single-channel PCM audio
            samples (no container/header) -- the smallest common
            denominator every engine can produce and every
            downstream consumer (WAV muxing in
            `parika.modules.voice.audio`) can consume uniformly.

        sample_rate:
            Sample rate, in Hz, of `pcm_bytes`.
    """

    pcm_bytes: bytes
    sample_rate: int


@runtime_checkable
class TtsEngine(Protocol):
    """
    Protocol implemented by every text-to-speech engine adapter usable
    by the Local Speech provider driver.
    """

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> TtsEngineResult:
        """
        Synthesize `text` into raw PCM audio.

        Args:
            text:
                Text to synthesize. Expected to already be one bounded
                chunk (e.g. one sentence); the engine itself performs
                no chunking.

            voice:
                Optional provider-specific voice/speaker identifier
                hint. `None` lets the engine use its configured
                default voice.

            language:
                Optional language hint (e.g. `"en"`, `"hi"`) selecting
                *which* configured voice to speak with, for an engine
                that holds more than one (see `PiperTtsEngine`'s own
                per-language voice selection). `None` lets the engine
                use its configured default/primary voice. An engine
                with only one voice configured simply ignores this.

        Returns:
            The normalized synthesis outcome.

        Raises:
            LocalSpeechExecutionError:
                If the engine fails to synthesize the supplied text
                (e.g. an internal engine failure).
        """
        ...
