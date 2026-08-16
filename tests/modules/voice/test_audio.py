"""
Unit tests for `parika.modules.voice.audio`.
"""

from __future__ import annotations

import pytest

from parika.modules.voice.audio import (
    concatenate_wav_chunks,
    pcm16_to_wav,
    wav_to_pcm16,
)
from parika.modules.voice.exceptions import VoiceProviderError


def test_pcm16_to_wav_round_trips_through_wav_to_pcm16() -> None:
    pcm = b"\x01\x00\x02\x00\x03\x00"

    wav_bytes = pcm16_to_wav(pcm, sample_rate=16000)
    decoded_pcm, sample_rate = wav_to_pcm16(wav_bytes)

    assert decoded_pcm == pcm
    assert sample_rate == 16000


def test_concatenate_wav_chunks_merges_pcm_in_order() -> None:
    chunk_one = pcm16_to_wav(b"\x01\x00", sample_rate=22050)
    chunk_two = pcm16_to_wav(b"\x02\x00", sample_rate=22050)

    merged_wav, sample_rate = concatenate_wav_chunks((chunk_one, chunk_two))
    merged_pcm, decoded_sample_rate = wav_to_pcm16(merged_wav)

    assert sample_rate == 22050
    assert decoded_sample_rate == 22050
    assert merged_pcm == b"\x01\x00\x02\x00"


def test_concatenate_empty_chunks_raises() -> None:
    with pytest.raises(VoiceProviderError):
        concatenate_wav_chunks(())


def test_concatenate_mismatched_sample_rates_raises() -> None:
    chunk_one = pcm16_to_wav(b"\x01\x00", sample_rate=16000)
    chunk_two = pcm16_to_wav(b"\x02\x00", sample_rate=22050)

    with pytest.raises(VoiceProviderError):
        concatenate_wav_chunks((chunk_one, chunk_two))
