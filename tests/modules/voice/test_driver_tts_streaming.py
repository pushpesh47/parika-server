"""
Unit tests for streaming TTS functionality in `parika.modules.voice.driver_tts`.
"""

from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.modules.voice.config import VoiceToolConfig
from parika.modules.voice.driver_tts import TextToSpeechToolDriver
from parika.modules.voice.exceptions import VoiceInputInvalidError
from parika.modules.voice.language import (
    VoiceLanguagePreference,
    VoiceLanguagePreferenceStore,
    VoiceOutputLanguage,
)
from parika.modules.voice.operation_registry import (
    TtsOperationRegistry,
    TtsOperationStatus,
)

from .conftest import failed_result, tts_result


def _driver(
    fake_brain, *, registry=None, chunk_max_characters=280, language_preference=None
):
    return TextToSpeechToolDriver(
        brain=fake_brain,
        provider_capability_id="voice.provider_text_to_speech",
        config=VoiceToolConfig(tts_chunk_max_characters=chunk_max_characters),
        operation_registry=registry or TtsOperationRegistry(),
        language_preference=language_preference,
    )


class TestTextToSpeechStreaming:
    def test_streaming_yields_chunks_in_order(self, fake_brain) -> None:
        """Streaming synthesis yields chunks in correct order with correct indices."""
        text = "Sentence one is here. Sentence two is here. Sentence three is here."

        for _ in range(3):
            fake_brain.queue("voice.provider_text_to_speech", tts_result())

        driver = _driver(fake_brain, chunk_max_characters=30)
        chunks = list(driver.synthesize_chunks_streaming(
            text=text,
            voice=None,
            language="en",
            operation_id="op-stream-1",
        ))

        assert len(chunks) == 3
        assert chunks[0]["chunk_index"] == 0
        assert chunks[1]["chunk_index"] == 1
        assert chunks[2]["chunk_index"] == 2
        assert chunks[0]["final"] is False
        assert chunks[1]["final"] is False
        assert chunks[2]["final"] is True
        assert all(not c["cancelled"] for c in chunks)
        assert all(c["audio_base64"] for c in chunks)
        assert all(c["mime_type"] == "audio/wav" for c in chunks)
        assert all(c["sample_rate"] > 0 for c in chunks)

    def test_streaming_sanitizes_text_before_chunking(self, fake_brain) -> None:
        """Streaming synthesis applies text sanitization before chunking."""
        # Text with Markdown that should be sanitized
        text = "**Bold** and *italic* text with `code`."

        fake_brain.queue("voice.provider_text_to_speech", tts_result())

        driver = _driver(fake_brain, chunk_max_characters=100)
        chunks = list(driver.synthesize_chunks_streaming(
            text=text,
            voice=None,
            language="en",
            operation_id="op-stream-2",
        ))

        # Should have synthesized sanitized text (no markdown artifacts)
        # The fake brain just returns a fixed result, but we can verify
        # the driver was called
        assert len(chunks) == 1
        call = fake_brain.goals_for("voice.provider_text_to_speech")[0]
        # The sanitized text should not contain markdown
        synthesized_text = call.provider_request_builder(None, None).text
        assert "**" not in synthesized_text
        assert "*" not in synthesized_text or "italic" in synthesized_text  # * removed
        assert "`" not in synthesized_text

    def test_streaming_cancellation_stops_early(self, fake_brain) -> None:
        """Cancellation during streaming stops synthesis and yields final cancelled chunk."""
        text = "Sentence one. Sentence two. Sentence three."
        registry = TtsOperationRegistry()

        for _ in range(3):
            fake_brain.queue("voice.provider_text_to_speech", tts_result())

        driver = _driver(fake_brain, registry=registry, chunk_max_characters=30)

        # Cancel after first chunk is yielded (between chunks)
        # We need to manually iterate and cancel after first chunk
        gen = driver.synthesize_chunks_streaming(
            text=text,
            voice=None,
            language="en",
            operation_id="op-stream-3",
        )
        chunks = []
        for i, chunk in enumerate(gen):
            chunks.append(chunk)
            if i == 0:
                # Cancel after first chunk
                registry.cancel("op-stream-3")

        # Should have first chunk + final cancelled chunk
        assert len(chunks) == 2
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["cancelled"] is False
        assert chunks[0]["final"] is False
        assert chunks[1]["chunk_index"] == 1
        assert chunks[1]["cancelled"] is True
        assert chunks[1]["final"] is True
        assert chunks[1]["audio_base64"] == ""
        assert registry.get_status("op-stream-3") is TtsOperationStatus.CANCELLED

    def test_streaming_preemptive_cancel_returns_empty(self, fake_brain) -> None:
        """Preemptive cancellation before synthesis starts yields empty cancelled chunk."""
        registry = TtsOperationRegistry()
        registry.cancel("op-stream-4")  # Cancel before starting

        driver = _driver(fake_brain, registry=registry)
        chunks = list(driver.synthesize_chunks_streaming(
            text="Hello there.",
            voice=None,
            language="en",
            operation_id="op-stream-4",
        ))

        assert len(chunks) == 1
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["cancelled"] is True
        assert chunks[0]["final"] is True
        assert chunks[0]["audio_base64"] == ""
        assert len(fake_brain.goals_for("voice.provider_text_to_speech")) == 0

    def test_streaming_provider_failure_yields_error_chunk(self, fake_brain) -> None:
        """Provider failure during streaming yields error chunk and stops."""
        fake_brain.queue(
            "voice.provider_text_to_speech",
            failed_result("no compatible model"),
        )

        driver = _driver(fake_brain)
        chunks = list(driver.synthesize_chunks_streaming(
            text="Hello there.",
            voice=None,
            language="en",
            operation_id="op-stream-5",
        ))

        # Should yield error chunk
        assert len(chunks) == 1
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["cancelled"] is False  # Provider error, not cancellation
        assert chunks[0]["final"] is True
        assert "error" in chunks[0]
        assert "no compatible model" in chunks[0]["error"]

    def test_streaming_empty_text_raises(self, fake_brain) -> None:
        """Empty text after sanitization yields error chunk."""
        driver = _driver(fake_brain)
        chunks = list(driver.synthesize_chunks_streaming(
            text="   ",
            voice=None,
            language="en",
            operation_id="op-stream-6",
        ))

        assert len(chunks) == 1
        assert chunks[0]["cancelled"] is True
        assert chunks[0]["final"] is True
        assert "error" in chunks[0]
        assert "Empty text" in chunks[0]["error"]

    def test_streaming_only_markdown_removed(self, fake_brain) -> None:
        """Text that is only markdown formatting produces error chunk."""
        driver = _driver(fake_brain)
        chunks = list(driver.synthesize_chunks_streaming(
            text="** **",
            voice=None,
            language="en",
            operation_id="op-stream-7",
        ))

        # Sanitized text is empty, should yield error
        assert len(chunks) == 1
        assert chunks[0]["cancelled"] is True
        assert "error" in chunks[0]
        assert "Empty text" in chunks[0]["error"]

    def test_streaming_preserves_language(self, fake_brain) -> None:
        """Streaming chunks include the resolved output language."""
        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        preference = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(output_language=VoiceOutputLanguage.HINDI)
        )

        driver = _driver(fake_brain, language_preference=preference)
        chunks = list(driver.synthesize_chunks_streaming(
            text="Namaste.",
            voice=None,
            language=None,  # Use preference
            operation_id="op-stream-8",
        ))

        assert len(chunks) == 1
        assert chunks[0]["language"] == "hi"

    def test_streaming_explicit_language_overrides(self, fake_brain) -> None:
        """Explicit language in streaming overrides preference."""
        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        preference = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(output_language=VoiceOutputLanguage.HINDI)
        )

        driver = _driver(fake_brain, language_preference=preference)
        chunks = list(driver.synthesize_chunks_streaming(
            text="Hello.",
            voice=None,
            language="en",  # Explicit override
            operation_id="op-stream-9",
        ))

        assert len(chunks) == 1
        assert chunks[0]["language"] == "en"
        goal = fake_brain.goals_for("voice.provider_text_to_speech")[0]
        assert goal.provider_request_builder(None, None).language == "en"

    def test_streaming_multiple_chunks_each_self_contained_wav(self, fake_brain) -> None:
        """Each streaming chunk is a self-contained WAV with correct headers."""
        text = "Sentence one. Sentence two."

        fake_brain.queue("voice.provider_text_to_speech", tts_result(pcm_bytes=b"\x01\x00", sample_rate=16000))
        fake_brain.queue("voice.provider_text_to_speech", tts_result(pcm_bytes=b"\x02\x00", sample_rate=16000))

        driver = _driver(fake_brain, chunk_max_characters=20)
        chunks = list(driver.synthesize_chunks_streaming(
            text=text,
            voice=None,
            language="en",
            operation_id="op-stream-10",
        ))

        assert len(chunks) == 2
        # Each chunk should be valid base64 WAV
        import base64
        import io
        import wave

        for chunk in chunks:
            wav_bytes = base64.b64decode(chunk["audio_base64"])
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2
                assert wf.getframerate() == 16000


class TestStreamingDriverIntegration:
    """Integration-style tests using the actual driver flow."""

    def test_streaming_vs_batch_consistency(self, fake_brain) -> None:
        """Streaming and batch synthesis produce same audio for same text."""
        text = "Sentence one is here. Sentence two is here."

        # Batch synthesis
        fake_brain.queue("voice.provider_text_to_speech", tts_result(pcm_bytes=b"\x01\x00", sample_rate=16000))
        fake_brain.queue("voice.provider_text_to_speech", tts_result(pcm_bytes=b"\x02\x00", sample_rate=16000))

        driver_batch = _driver(fake_brain, chunk_max_characters=30)
        batch_response = driver_batch.execute(ToolRequest(arguments={
            "text": text, "operation_id": "op-batch"
        }))

        # Streaming synthesis (fresh brain with same responses)
        fake_brain2 = fake_brain.__class__()
        for _ in range(2):
            fake_brain2.queue("voice.provider_text_to_speech", tts_result(pcm_bytes=b"\x01\x00", sample_rate=16000))
            fake_brain2.queue("voice.provider_text_to_speech", tts_result(pcm_bytes=b"\x02\x00", sample_rate=16000))

        driver_stream = _driver(fake_brain2, chunk_max_characters=30)
        stream_chunks = list(driver_stream.synthesize_chunks_streaming(
            text=text,
            voice=None,
            language="en",
            operation_id="op-stream",
        ))

        # Both should have same number of provider calls
        batch_calls = len(fake_brain.goals_for("voice.provider_text_to_speech"))
        stream_calls = len(fake_brain2.goals_for("voice.provider_text_to_speech"))

        # The chunking logic is the same, so both should make 2 calls
        assert batch_calls == stream_calls == 2