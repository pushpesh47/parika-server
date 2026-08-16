"""
PARIKA Local Speech Provider - WAV Encoding

Encodes raw, 16-bit mono PCM samples (the normalized shape every
`TtsEngine` returns -- see `engines/tts_engine.py`) into a self-
contained WAV file, using only the Python standard library's `wave`
module -- no new dependency.

`SpeechResult.audio_base64` (the provider-independent boundary type)
always carries a fully self-describing WAV file, never bare PCM, for
the same reason `GeneratedArtifact.content_base64` always carries a
self-describing image/video file: every provider-independent consumer
must be able to interpret the bytes using only `SpeechResult
.audio_mime_type`, with no out-of-band sample-rate/channel-count
knowledge required.
"""

from __future__ import annotations

import io
import wave


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
