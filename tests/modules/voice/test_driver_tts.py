"""
Unit tests for `parika.modules.voice.driver_tts`, using `FakeBrain`.
"""

from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.modules.voice.audio import wav_to_pcm16
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

from .conftest import failed_result, tts_result, write_result


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


class TestTextToSpeechToolDriver:
    def test_synthesizes_short_text_in_one_chunk(self, fake_brain) -> None:
        fake_brain.queue("voice.provider_text_to_speech", tts_result())

        driver = _driver(fake_brain)
        response = driver.execute(ToolRequest(arguments={"text": "Hello there."}))

        assert response.result["cancelled"] is False
        assert response.result["mime_type"] == "audio/wav"
        assert response.result["audio_base64"]
        assert len(fake_brain.goals_for("voice.provider_text_to_speech")) == 1

    def test_rejects_empty_text(self, fake_brain) -> None:
        driver = _driver(fake_brain)

        with pytest.raises(VoiceInputInvalidError):
            driver.execute(ToolRequest(arguments={"text": "   "}))

    def test_chunks_long_text_into_multiple_provider_calls(self, fake_brain) -> None:
        text = "Sentence one is here. Sentence two is here. Sentence three is here."

        for _ in range(3):
            fake_brain.queue("voice.provider_text_to_speech", tts_result())

        driver = _driver(fake_brain, chunk_max_characters=30)
        response = driver.execute(ToolRequest(arguments={"text": text}))

        calls = fake_brain.goals_for("voice.provider_text_to_speech")
        assert len(calls) == 3
        assert response.result["cancelled"] is False

    def test_cancellation_between_chunks_stops_early_and_returns_partial_audio(
        self, fake_brain
    ) -> None:
        text = "Sentence one is here. Sentence two is here. Sentence three is here."
        registry = TtsOperationRegistry()

        for _ in range(3):
            fake_brain.queue("voice.provider_text_to_speech", tts_result())

        driver = _driver(fake_brain, registry=registry, chunk_max_characters=30)

        # Cancel after the underlying provider goal for the *first*
        # chunk has already been dispatched by monkeypatching the
        # queue consumption is awkward here, so instead cancel via a
        # FakeBrain wrapper that cancels on its second call.
        original_handle = fake_brain.handle
        call_count = {"n": 0}

        def _handle(request):
            call_count["n"] += 1
            if call_count["n"] == 2:
                registry.cancel("op-1")
            return original_handle(request)

        fake_brain.handle = _handle

        response = driver.execute(
            ToolRequest(arguments={"text": text, "operation_id": "op-1"})
        )

        assert response.result["cancelled"] is True
        assert response.result["operation_id"] == "op-1"
        # Only the first two chunks were ever dispatched: the guard
        # checked before the third call and stopped early.
        assert call_count["n"] == 2
        assert registry.get_status("op-1") is TtsOperationStatus.CANCELLED
        # Partial audio (from the chunks synthesized before
        # cancellation) is still returned, never dropped.
        assert response.result["audio_base64"]

    def test_preemptive_cancel_before_synthesis_starts_produces_no_audio(
        self, fake_brain
    ) -> None:
        registry = TtsOperationRegistry()
        registry.cancel("op-1")  # cancel before the operation ever begins

        driver = _driver(fake_brain, registry=registry)
        response = driver.execute(
            ToolRequest(arguments={"text": "Hello there.", "operation_id": "op-1"})
        )

        assert response.result["cancelled"] is True
        assert response.result["audio_base64"] == ""
        assert len(fake_brain.goals_for("voice.provider_text_to_speech")) == 0

    def test_provider_failure_marks_operation_failed_and_raises(self, fake_brain) -> None:
        fake_brain.queue(
            "voice.provider_text_to_speech",
            failed_result("no compatible text-to-speech model is installed"),
        )
        registry = TtsOperationRegistry()

        driver = _driver(fake_brain, registry=registry)

        with pytest.raises(Exception):
            driver.execute(
                ToolRequest(arguments={"text": "Hello there.", "operation_id": "op-1"})
            )

        assert registry.get_status("op-1") is TtsOperationStatus.FAILED

    def test_writes_output_file_when_output_path_supplied(self, fake_brain) -> None:
        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        fake_brain.queue("filesystem.write", write_result(path="/tmp/out.wav"))

        driver = _driver(fake_brain)
        response = driver.execute(
            ToolRequest(arguments={"text": "Hello.", "output_path": "/tmp/out.wav"})
        )

        assert response.result["output_path"] == "/tmp/out.wav"
        write_goal = fake_brain.goals_for("filesystem.write")[0]
        assert write_goal.inputs["path"] == "/tmp/out.wav"

    def test_explicit_output_language_overrides_the_current_preference(
        self, fake_brain
    ) -> None:
        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        preference = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(output_language=VoiceOutputLanguage.HINDI)
        )

        driver = _driver(fake_brain, language_preference=preference)
        response = driver.execute(
            ToolRequest(arguments={"text": "Hello there.", "language": "en"})
        )

        assert response.result["language"] == "en"
        goal = fake_brain.goals_for("voice.provider_text_to_speech")[0]
        assert goal.provider_request_builder(None, None).language == "en"

    def test_output_language_preference_is_used_when_request_omits_one(
        self, fake_brain
    ) -> None:
        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        preference = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(output_language=VoiceOutputLanguage.HINDI)
        )

        driver = _driver(fake_brain, language_preference=preference)
        response = driver.execute(ToolRequest(arguments={"text": "Namaste."}))

        assert response.result["language"] == "hi"

    def test_follow_input_resolves_against_last_detected_input_language(
        self, fake_brain
    ) -> None:
        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        preference = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(
                output_language=VoiceOutputLanguage.FOLLOW_INPUT
            )
        )
        preference.record_detected_input_language("hi")

        driver = _driver(fake_brain, language_preference=preference)
        response = driver.execute(ToolRequest(arguments={"text": "Namaste."}))

        assert response.result["language"] == "hi"

    def test_follow_input_falls_back_to_default_language_before_any_input(
        self, fake_brain
    ) -> None:
        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        preference = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(
                output_language=VoiceOutputLanguage.FOLLOW_INPUT
            )
        )

        driver = _driver(fake_brain, language_preference=preference)
        response = driver.execute(ToolRequest(arguments={"text": "Hello there."}))

        assert response.result["language"] == "en"

    def test_language_change_between_two_speak_calls_does_not_affect_the_first(
        self, fake_brain
    ) -> None:
        """
        Section 9/13: changing the current output-language preference
        must never retroactively affect an operation that has already
        resolved its language (mirrors the existing dynamic-output-
        preference principle -- only the *next* operation observes a
        preference change).
        """

        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        fake_brain.queue("voice.provider_text_to_speech", tts_result())
        preference = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(output_language=VoiceOutputLanguage.ENGLISH)
        )

        driver = _driver(fake_brain, language_preference=preference)
        first = driver.execute(ToolRequest(arguments={"text": "Hello."}))

        preference.set_output_language(VoiceOutputLanguage.HINDI)
        second = driver.execute(ToolRequest(arguments={"text": "Namaste."}))

        assert first.result["language"] == "en"
        assert second.result["language"] == "hi"

    def test_concatenated_audio_preserves_chunk_pcm_order(self, fake_brain) -> None:
        text = "Sentence one is here. Sentence two is here."

        fake_brain.queue(
            "voice.provider_text_to_speech",
            tts_result(pcm_bytes=b"\x01\x00", sample_rate=16000),
        )
        fake_brain.queue(
            "voice.provider_text_to_speech",
            tts_result(pcm_bytes=b"\x02\x00", sample_rate=16000),
        )

        driver = _driver(fake_brain, chunk_max_characters=30)
        response = driver.execute(ToolRequest(arguments={"text": text}))

        import base64

        merged_pcm, sample_rate = wav_to_pcm16(
            base64.b64decode(response.result["audio_base64"])
        )
        assert merged_pcm == b"\x01\x00\x02\x00"
        assert sample_rate == 16000
