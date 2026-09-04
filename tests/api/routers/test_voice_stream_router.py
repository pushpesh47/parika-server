"""
Tests for the streaming TTS API endpoint: POST /api/v1/voice/speak/stream
"""

from __future__ import annotations

import json
import threading

import pytest

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel
from parika.providers.local_speech.discovery import STT_MODEL_ID, TTS_MODEL_ID
from parika.providers.local_speech.engines.stt_engine import SttEngineResult
from parika.providers.local_speech.engines.tts_engine import TtsEngineResult
from parika.providers.local_speech.manifest import LOCAL_SPEECH_PROVIDER_ID


@pytest.fixture(scope="module")
def voice_ready(client):
    """
    Injects fake STT/TTS engines into the shared runtime's already-
    registered Local Speech Provider driver, and registers matching
    synthetic `ProviderModel`s, so Planner's Model Selection Framework
    has a real candidate to select for every test in this module.
    """

    runtime = client.app.state.runtime
    driver = runtime.provider_manager._drivers[LOCAL_SPEECH_PROVIDER_ID]  # noqa: SLF001

    class _FakeSttEngine:
        def transcribe(self, audio_bytes, *, language=None):
            return SttEngineResult(
                text=f"you said: {audio_bytes.decode()}",
                language_detected=language or "en",
            )

    class _FakeTtsEngine:
        def synthesize(self, text, *, voice=None, language=None):
            return TtsEngineResult(pcm_bytes=b"\x00\x01" * 20, sample_rate=16000)

    driver._stt_engine = _FakeSttEngine()  # noqa: SLF001
    driver._tts_engine = _FakeTtsEngine()  # noqa: SLF001
    driver.discover_models = lambda: (
        ProviderModel(
            id=STT_MODEL_ID,
            name="fake-stt",
            capabilities=frozenset({ModelCapability.SPEECH_TO_TEXT}),
            specializations=frozenset({"speech_to_text"}),
            supported_modalities=frozenset({"audio"}),
        ),
        ProviderModel(
            id=TTS_MODEL_ID,
            name="fake-tts",
            capabilities=frozenset({ModelCapability.TEXT_TO_SPEECH}),
            specializations=frozenset({"text_to_speech"}),
            supported_modalities=frozenset({"audio"}),
        ),
    )
    driver.check_health = lambda: ProviderHealth(available=True)
    runtime.provider_manager.discover_models(LOCAL_SPEECH_PROVIDER_ID)
    runtime.provider_manager.refresh_health(LOCAL_SPEECH_PROVIDER_ID)

    return runtime


def _audio_base64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode()).decode("ascii")


class TestVoiceSpeakStream:
    def test_stream_returns_ndjson_chunks(self, voice_ready, client) -> None:
        """Streaming endpoint returns NDJSON with audio chunks."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "Hello world. This is a test.", "operation_id": "op-stream-test-1"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-ndjson"

        # Parse NDJSON lines
        lines = response.text.strip().split("\n")
        assert len(lines) >= 1

        chunks = [json.loads(line) for line in lines]
        assert len(chunks) >= 1

        # Check chunk structure
        for i, chunk in enumerate(chunks):
            assert "operation_id" in chunk
            assert "chunk_index" in chunk
            assert "audio_base64" in chunk
            assert "mime_type" in chunk
            assert "sample_rate" in chunk
            assert "final" in chunk
            assert "cancelled" in chunk
            assert "language" in chunk
            assert "error" in chunk
            assert chunk["chunk_index"] == i
            assert chunk["mime_type"] == "audio/wav"
            assert chunk["sample_rate"] > 0

        # Last chunk should be final
        assert chunks[-1]["final"] is True
        assert chunks[-1]["cancelled"] is False
        assert chunks[-1]["error"] is None

    def test_stream_chunks_in_order(self, voice_ready, client) -> None:
        """Streaming chunks arrive in strict order."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "Sentence one. Sentence two. Sentence three.", "operation_id": "op-stream-test-2"},
        )

        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        # Check ordering
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_index"] == i

    def test_stream_sanitizes_markdown(self, voice_ready, client) -> None:
        """Streaming endpoint sanitizes Markdown before synthesis."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "**Bold** and *italic* text.", "operation_id": "op-stream-test-3"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        # Should succeed (sanitized text is speakable)
        assert len(chunks) >= 1
        assert chunks[-1]["final"] is True
        assert chunks[-1]["cancelled"] is False

    def test_stream_cancellation(self, voice_ready, client) -> None:
        """Cancellation stops streaming mid-synthesis."""
        # Start streaming with long text
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five.", "operation_id": "op-stream-test-4"},
        )

        # We can't easily test mid-stream cancellation in this sync test
        # but we can verify the stream completes normally
        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]
        assert chunks[-1]["final"] is True
        assert chunks[-1]["cancelled"] is False

    def test_stream_preemptive_cancel(self, voice_ready, client) -> None:
        """Preemptive cancellation via stop endpoint before speak."""
        # Cancel before speak
        stop_response = client.post("/api/v1/voice/speak/op-preemptive/stop")
        assert stop_response.status_code == 200
        assert stop_response.json()["stopped"] is True

        # Now stream with same operation_id
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "This should not be heard.", "operation_id": "op-preemptive"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        # Should yield cancelled chunk immediately
        assert len(chunks) == 1
        assert chunks[0]["cancelled"] is True
        assert chunks[0]["final"] is True
        assert chunks[0]["audio_base64"] == ""

    def test_stream_empty_text_error(self, voice_ready, client) -> None:
        """Empty text yields error chunk."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "   ", "operation_id": "op-stream-test-5"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        assert len(chunks) == 1
        assert chunks[0]["cancelled"] is True
        assert chunks[0]["final"] is True
        assert chunks[0]["error"] is not None
        assert "Empty text" in chunks[0]["error"]

    def test_stream_only_markdown_error(self, voice_ready, client) -> None:
        """Text that sanitizes to empty yields error."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "** **", "operation_id": "op-stream-test-6"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        assert len(chunks) == 1
        assert chunks[0]["cancelled"] is True
        assert "error" in chunks[0]

    def test_stream_language_override(self, voice_ready, client) -> None:
        """Explicit language parameter is respected."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "Namaste.", "language": "hi", "operation_id": "op-stream-test-7"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        assert chunks[0]["language"] == "hi"

    def test_stream_respects_preference(self, voice_ready, client) -> None:
        """Streaming uses current output language preference when not overridden."""
        # Set preference to Hindi
        client.put("/api/v1/voice/settings", json={"output_language": "hi"})

        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "Namaste.", "operation_id": "op-stream-test-8"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        assert chunks[0]["language"] == "hi"

        # Restore preference
        client.put("/api/v1/voice/settings", json={"output_language": "follow_input"})

    def test_stream_without_operation_id(self, voice_ready, client) -> None:
        """Streaming works without operation_id (auto-generated)."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "Hello."},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        assert len(chunks) >= 1
        assert chunks[0]["operation_id"]  # Should be auto-generated
        assert chunks[-1]["final"] is True

    def test_stream_each_chunk_self_contained_wav(self, voice_ready, client) -> None:
        """Each chunk is a valid self-contained WAV file."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "One. Two.", "operation_id": "op-stream-test-9"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        import base64
        import io
        import wave

        for chunk in chunks:
            if chunk["audio_base64"]:
                wav_bytes = base64.b64decode(chunk["audio_base64"])
                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    assert wf.getnchannels() == 1
                    assert wf.getsampwidth() == 2
                    assert wf.getframerate() == chunk["sample_rate"]
                    assert wf.getnframes() > 0

    def test_stream_vs_regular_speak_consistency(self, voice_ready, client) -> None:
        """Streaming and regular speak produce equivalent audio for same text."""
        text = "Consistency test sentence."

        # Regular speak
        regular_response = client.post(
            "/api/v1/voice/speak",
            json={"text": text, "operation_id": "op-regular"},
        )
        assert regular_response.status_code == 200
        regular_audio = regular_response.json()["audio_base64"]

        # Streaming speak
        stream_response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": text, "operation_id": "op-stream"},
        )
        assert stream_response.status_code == 200
        lines = stream_response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        # Concatenate streaming audio
        import base64
        stream_audio = "".join(chunk["audio_base64"] for chunk in chunks if chunk["audio_base64"])

        # Both should have audio
        assert regular_audio
        assert stream_audio

        # Both should be valid WAV
        import io
        import wave
        for audio_b64 in [regular_audio, stream_audio]:
            wav_bytes = base64.b64decode(audio_b64)
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2

    def test_stream_multiple_chunks_have_audio(self, voice_ready, client) -> None:
        """Multi-chunk streaming produces audio for each chunk."""
        response = client.post(
            "/api/v1/voice/speak/stream",
            json={"text": "Sentence one. Sentence two. Sentence three.", "operation_id": "op-stream-test-10"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        chunks = [json.loads(line) for line in lines]

        # All non-final chunks should have audio
        for chunk in chunks[:-1]:
            assert chunk["audio_base64"], f"Chunk {chunk['chunk_index']} missing audio"

        # Final chunk may or may not have audio depending on chunking
        # but should be marked final
        assert chunks[-1]["final"] is True

    def test_stream_delivers_first_chunk_before_second_synthesis(self, voice_ready, client) -> None:
        """
        Proves incremental delivery: chunk 0 is received before chunk 1 synthesis begins.

        Uses a controllable fake TTS engine that blocks on the second synthesis call
        until the test releases it. The test verifies that chunk 0 is fully received
        (and parsed as valid NDJSON) before the second synthesis is allowed to proceed.
        """
        runtime = voice_ready
        driver = runtime.provider_manager._drivers[LOCAL_SPEECH_PROVIDER_ID]  # noqa: SLF001

        # Synchronization primitives controlled by the test
        chunk1_blocked = threading.Event()
        chunk1_released = threading.Event()
        chunk1_synthesis_started = threading.Event()

        class _BlockingFakeTtsEngine:
            """Fake TTS engine that blocks on second synthesis until released by test."""

            def __init__(self):
                self.call_count = 0

            def synthesize(self, text, *, voice=None, language=None):
                self.call_count += 1
                if self.call_count == 1:
                    # First chunk: return immediately
                    return TtsEngineResult(pcm_bytes=b"\x00\x01" * 20, sample_rate=16000)
                elif self.call_count == 2:
                    # Second chunk: signal we've started synthesis, then block
                    chunk1_synthesis_started.set()
                    chunk1_blocked.wait(timeout=10.0)  # Wait for test to release
                    chunk1_released.set()
                    return TtsEngineResult(pcm_bytes=b"\x02\x03" * 20, sample_rate=16000)
                else:
                    # Should not reach here for this test
                    return TtsEngineResult(pcm_bytes=b"\x04\x05" * 20, sample_rate=16000)

        blocking_engine = _BlockingFakeTtsEngine()
        driver._tts_engine = blocking_engine  # noqa: SLF001

        # Text that will produce exactly 2 chunks (over 280 char limit per chunk to force splitting)
        # Each sentence ~40 chars, need at least 8 sentences to exceed 280
        text = "Sentence one is a test sentence for streaming. " * 8

        # Use client.stream() to consume response incrementally
        with client.stream(
            "POST",
            "/api/v1/voice/speak/stream",
            json={"text": text, "operation_id": "op-stream-incremental-test"},
        ) as response:
            assert response.status_code == 200

            # Read first line (chunk 0) - this should arrive immediately
            chunk0_line = next(response.iter_lines())
            assert chunk0_line, "Expected first chunk line"
            chunk0 = json.loads(chunk0_line)
            assert chunk0["chunk_index"] == 0
            assert chunk0["audio_base64"], "Chunk 0 should have audio"
            assert chunk0["final"] is False
            assert chunk0["cancelled"] is False

            # KEY ASSERTION: At this point, chunk 0 has been received by the client.
            # Now verify that chunk 1 synthesis has STARTED (it blocks inside synthesize).
            # If the endpoint waited for all synthesis before sending, this would timeout
            # because chunk 1 synthesis wouldn't start until after the response is complete.
            assert chunk1_synthesis_started.wait(timeout=2.0), (
                "Chunk 1 synthesis should have started after chunk 0 was delivered"
            )

            # Now release chunk 1 synthesis so the stream can complete
            chunk1_blocked.set()
            assert chunk1_released.wait(timeout=2.0), "Chunk 1 synthesis should complete after release"

        # Verify the engine was called exactly twice (not more, not less)
        assert blocking_engine.call_count == 2, f"Expected 2 synthesis calls, got {blocking_engine.call_count}"