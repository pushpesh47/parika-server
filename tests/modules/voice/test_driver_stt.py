"""
Unit tests for `parika.modules.voice.driver_stt`, using `FakeBrain`.
"""

from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.modules.voice.driver_stt import SpeechToTextToolDriver
from parika.modules.voice.exceptions import VoiceInputInvalidError, VoiceProviderError
from parika.modules.voice.language import (
    VoiceInputLanguage,
    VoiceLanguagePreference,
    VoiceLanguagePreferenceStore,
)

from .conftest import AUDIO_BASE64, failed_result, read_result, stt_result


class TestSpeechToTextToolDriver:
    def test_transcribes_from_inline_audio_base64(self, fake_brain) -> None:
        fake_brain.queue("voice.provider_speech_to_text", stt_result(text="hello there"))

        driver = SpeechToTextToolDriver(
            brain=fake_brain, provider_capability_id="voice.provider_speech_to_text"
        )
        response = driver.execute(ToolRequest(arguments={"audio_base64": AUDIO_BASE64}))

        assert response.result["text"] == "hello there"
        assert response.result["language"] == "en"

    def test_transcribes_from_a_file_path_via_filesystem_read(self, fake_brain) -> None:
        fake_brain.queue("filesystem.read", read_result())
        fake_brain.queue("voice.provider_speech_to_text", stt_result())

        driver = SpeechToTextToolDriver(
            brain=fake_brain, provider_capability_id="voice.provider_speech_to_text"
        )
        response = driver.execute(ToolRequest(arguments={"path": "/tmp/in.wav"}))

        assert response.result["text"] == "hello world"
        assert fake_brain.goals_for("filesystem.read")[0].inputs["path"] == "/tmp/in.wav"

    def test_rejects_missing_audio_and_path(self, fake_brain) -> None:
        driver = SpeechToTextToolDriver(
            brain=fake_brain, provider_capability_id="voice.provider_speech_to_text"
        )

        with pytest.raises(VoiceInputInvalidError):
            driver.execute(ToolRequest(arguments={}))

    def test_provider_failure_raises_voice_provider_error(self, fake_brain) -> None:
        fake_brain.queue(
            "voice.provider_speech_to_text",
            failed_result("no compatible speech-to-text model is installed"),
        )

        driver = SpeechToTextToolDriver(
            brain=fake_brain, provider_capability_id="voice.provider_speech_to_text"
        )

        with pytest.raises(VoiceProviderError):
            driver.execute(ToolRequest(arguments={"audio_base64": AUDIO_BASE64}))

    def test_passes_through_language_hint(self, fake_brain) -> None:
        fake_brain.queue("voice.provider_speech_to_text", stt_result(language="hi"))

        driver = SpeechToTextToolDriver(
            brain=fake_brain, provider_capability_id="voice.provider_speech_to_text"
        )
        driver.execute(
            ToolRequest(arguments={"audio_base64": AUDIO_BASE64, "language": "hi"})
        )

        goal = fake_brain.goals_for("voice.provider_speech_to_text")[0]
        built_request = goal.provider_request_builder(None, None)

        assert built_request.language == "hi"

    def test_explicit_language_reports_explicit_source(self, fake_brain) -> None:
        fake_brain.queue("voice.provider_speech_to_text", stt_result(language="hi"))

        driver = SpeechToTextToolDriver(
            brain=fake_brain, provider_capability_id="voice.provider_speech_to_text"
        )
        response = driver.execute(
            ToolRequest(arguments={"audio_base64": AUDIO_BASE64, "language": "hi"})
        )

        assert response.result["requested_input_language"] == "hi"
        assert response.result["detected_input_language"] == "hi"
        assert response.result["language_source"] == "explicit"

    def test_auto_mode_omits_language_hint_and_reports_detected_language(
        self, fake_brain
    ) -> None:
        fake_brain.queue("voice.provider_speech_to_text", stt_result(language="en"))

        driver = SpeechToTextToolDriver(
            brain=fake_brain, provider_capability_id="voice.provider_speech_to_text"
        )
        driver.execute(ToolRequest(arguments={"audio_base64": AUDIO_BASE64}))

        goal = fake_brain.goals_for("voice.provider_speech_to_text")[0]
        built_request = goal.provider_request_builder(None, None)

        assert built_request.language is None

    def test_current_input_language_preference_is_used_when_request_omits_one(
        self, fake_brain
    ) -> None:
        fake_brain.queue("voice.provider_speech_to_text", stt_result(language="hi"))
        preference = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(input_language=VoiceInputLanguage.HINDI)
        )

        driver = SpeechToTextToolDriver(
            brain=fake_brain,
            provider_capability_id="voice.provider_speech_to_text",
            language_preference=preference,
        )
        driver.execute(ToolRequest(arguments={"audio_base64": AUDIO_BASE64}))

        goal = fake_brain.goals_for("voice.provider_speech_to_text")[0]
        built_request = goal.provider_request_builder(None, None)

        assert built_request.language == "hi"

    def test_unsupported_detected_language_is_flagged_not_silently_relabeled(
        self, fake_brain
    ) -> None:
        fake_brain.queue("voice.provider_speech_to_text", stt_result(language="fr"))

        driver = SpeechToTextToolDriver(
            brain=fake_brain, provider_capability_id="voice.provider_speech_to_text"
        )
        response = driver.execute(
            ToolRequest(arguments={"audio_base64": AUDIO_BASE64})
        )

        assert response.result["detected_input_language"] == "fr"
        assert response.result["language_source"] == "unsupported"
        assert response.attributes["language_supported"] is False

    def test_records_detected_language_into_the_shared_preference_store(
        self, fake_brain
    ) -> None:
        fake_brain.queue("voice.provider_speech_to_text", stt_result(language="hi"))
        preference = VoiceLanguagePreferenceStore()

        driver = SpeechToTextToolDriver(
            brain=fake_brain,
            provider_capability_id="voice.provider_speech_to_text",
            language_preference=preference,
        )
        driver.execute(ToolRequest(arguments={"audio_base64": AUDIO_BASE64}))

        assert preference.get().last_detected_input_language == "hi"
