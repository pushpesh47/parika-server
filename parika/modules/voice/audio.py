"""
PARIKA Voice Module - WAV Concatenation

Merges the per-chunk WAV files `text_to_speech`'s chunked synthesis
loop (`driver_tts.py`) produces (one provider-independent
`SpeechResult.audio_base64` per text chunk, per
`text_chunking.split_into_speech_chunks()`) back into one WAV file, by
decoding each chunk's raw PCM samples and re-encoding once, using only
the Python standard library's `wave` module -- no new dependency.

This Module never assumes a specific engine's sample rate/channel
count; every value is read back from each chunk's own WAV header, and
chunks are required to share the same sample rate (they always do --
every chunk is synthesized by the very same Provider Capability call
in the same `speak` operation).
"""

from __future__ import annotations

import io
import wave

from .exceptions import VoiceProviderError


def wav_to_pcm16(wav_bytes: bytes) -> tuple[bytes, int]:
    """
    Decode one WAV file into its raw 16-bit PCM samples and sample
    rate.
    """

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        pcm_bytes = wav_file.readframes(wav_file.getnframes())

    return pcm_bytes, sample_rate


def pcm16_to_wav(pcm_bytes: bytes, *, sample_rate: int, channels: int = 1) -> bytes:
    """
    Encode raw 16-bit signed little-endian PCM samples into a WAV
    file.
    """

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)

    return buffer.getvalue()


def concatenate_wav_chunks(wav_chunks: tuple[bytes, ...]) -> tuple[bytes, int]:
    """
    Concatenate an ordered tuple of WAV-encoded audio chunks into one
    WAV file.

    Returns:
        `(wav_bytes, sample_rate)`.

    Raises:
        VoiceProviderError:
            If `wav_chunks` is empty, or the chunks do not share one
            sample rate.
    """

    if not wav_chunks:
        raise VoiceProviderError(
            "Cannot build synthesized audio from zero chunks."
        )

    sample_rate: int | None = None
    pcm_pieces: list[bytes] = []

    for chunk in wav_chunks:
        pcm_bytes, chunk_sample_rate = wav_to_pcm16(chunk)

        if sample_rate is None:
            sample_rate = chunk_sample_rate
        elif chunk_sample_rate != sample_rate:
            raise VoiceProviderError(
                "Synthesized audio chunks do not share one sample "
                f"rate ({sample_rate} vs {chunk_sample_rate})."
            )

        pcm_pieces.append(pcm_bytes)

    assert sample_rate is not None  # noqa: S101 -- guaranteed non-empty above

    return pcm16_to_wav(b"".join(pcm_pieces), sample_rate=sample_rate), sample_rate
