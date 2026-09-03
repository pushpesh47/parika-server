"""
Tests for `POST /api/v1/voice/transcribe`, `POST /api/v1/voice/respond`,
`POST /api/v1/voice/speak`, and `POST /api/v1/voice/speak/{operation_id}
/stop`.

No real `faster-whisper`/Kokoro installation is required: the shared
`client` fixture's runtime registers the Local Speech Provider with
zero discovered models (neither optional dependency is installed in
this environment), so these tests inject fake `SttEngine`/`TtsEngine`
implementations directly onto the already-constructed
`LocalSpeechProviderDriver` and register matching synthetic
`ProviderModel`s -- exactly the same "engine is provider/engine
isolated, so a fake engine is a legitimate test double" seam
`parika.providers.local_speech.engines` exists for.
"""

from __future__ import annotations

import base64

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
    return base64.b64encode(text.encode()).decode("ascii")


def test_transcribe_returns_text(voice_ready, client) -> None:
    response = client.post(
        "/api/v1/voice/transcribe",
        json={"audio_base64": _audio_base64("hello")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "you said: hello"
    assert body["language"] == "en"


def test_transcribe_passes_through_language_hint(voice_ready, client) -> None:
    response = client.post(
        "/api/v1/voice/transcribe",
        json={"audio_base64": _audio_base64("namaste"), "language": "hi"},
    )

    assert response.status_code == 200
    assert response.json()["language"] == "hi"


def test_transcribe_reports_full_language_metadata_for_explicit_language(
    voice_ready, client
) -> None:
    response = client.post(
        "/api/v1/voice/transcribe",
        json={"audio_base64": _audio_base64("namaste"), "language": "hi"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_input_language"] == "hi"
    assert body["detected_input_language"] == "hi"
    assert body["language_source"] == "explicit"


def test_transcribe_reports_auto_language_source_by_default(voice_ready, client) -> None:
    response = client.post(
        "/api/v1/voice/transcribe",
        json={"audio_base64": _audio_base64("hello")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_input_language"] == "auto"
    assert body["language_source"] == "auto"


def test_transcribe_rejects_unsupported_language(voice_ready, client) -> None:
    response = client.post(
        "/api/v1/voice/transcribe",
        json={"audio_base64": _audio_base64("bonjour"), "language": "fr"},
    )

    assert response.status_code == 422


def test_speak_returns_audio_and_operation_id(voice_ready, client) -> None:
    response = client.post(
        "/api/v1/voice/speak",
        json={"text": "Hello there.", "operation_id": "op-speak-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_id"] == "op-speak-1"
    assert body["mime_type"] == "audio/wav"
    assert body["cancelled"] is False
    assert body["audio_base64"]


def test_speak_without_operation_id_still_succeeds(voice_ready, client) -> None:
    response = client.post("/api/v1/voice/speak", json={"text": "Hi."})

    assert response.status_code == 200
    assert response.json()["operation_id"]


def test_speak_reports_the_resolved_output_language(voice_ready, client) -> None:
    response = client.post(
        "/api/v1/voice/speak",
        json={"text": "Namaste.", "language": "hi", "operation_id": "op-lang-1"},
    )

    assert response.status_code == 200
    assert response.json()["output_language"] == "hi"


def test_speak_rejects_unsupported_output_language(voice_ready, client) -> None:
    response = client.post(
        "/api/v1/voice/speak",
        json={"text": "Hello.", "language": "auto"},
    )

    assert response.status_code == 422


def test_stop_speaking_after_completion_returns_false(voice_ready, client) -> None:
    speak_response = client.post(
        "/api/v1/voice/speak",
        json={"text": "Hello there.", "operation_id": "op-already-done"},
    )
    assert speak_response.status_code == 200

    stop_response = client.post(
        "/api/v1/voice/speak/op-already-done/stop"
    )

    assert stop_response.status_code == 200
    body = stop_response.json()
    assert body["operation_id"] == "op-already-done"
    assert body["stopped"] is False


def test_stop_speaking_preemptively_before_speak_is_called(voice_ready, client) -> None:
    stop_response = client.post("/api/v1/voice/speak/op-not-started-yet/stop")

    assert stop_response.status_code == 200
    assert stop_response.json()["stopped"] is True

    speak_response = client.post(
        "/api/v1/voice/speak",
        json={"text": "This should never be heard.", "operation_id": "op-not-started-yet"},
    )

    assert speak_response.status_code == 200
    body = speak_response.json()
    assert body["cancelled"] is True
    assert body["audio_base64"] == ""


def test_respond_transcribes_and_submits_through_the_same_chat_pipeline(
    voice_ready, client, monkeypatch
) -> None:
    """
    Proves `voice.respond` transcribes audio and then calls the exact
    same `handle_chat()` function `POST /api/v1/chat` uses -- never a
    second reasoning pipeline (Section 16).
    """

    from parika.api.handlers import voice as voice_handlers

    recorded_calls = []
    original_handle_chat = voice_handlers.handle_chat

    def _recording_handle_chat(runtime, session_store, request):
        recorded_calls.append(request)
        return original_handle_chat(runtime, session_store, request)

    monkeypatch.setattr(voice_handlers, "handle_chat", _recording_handle_chat)

    response = client.post(
        "/api/v1/voice/respond",
        json={"audio_base64": _audio_base64("hello"), "session_id": "s-voice-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "s-voice-1"
    assert body["transcript"] == "you said: hello"

    assert len(recorded_calls) == 1
    assert recorded_calls[0].text == "you said: hello"
    assert recorded_calls[0].session_id == "s-voice-1"

    # The exact same session the typed chat endpoint would also reuse.
    chat_response = client.post(
        "/api/v1/chat", json={"text": "again", "session_id": "s-voice-1"}
    )
    assert chat_response.json()["session_id"] == "s-voice-1"


def test_respond_never_triggers_text_to_speech(voice_ready, client, monkeypatch) -> None:
    """
    Section 8/9: the canonical response is always text; `voice.respond`
    must never call the text-to-speech Tool itself.
    """

    calls: list[str] = []
    original_execute = voice_ready.tool_manager.execute

    def _recording_execute(tool_id, request):
        calls.append(tool_id)
        return original_execute(tool_id, request)

    monkeypatch.setattr(voice_ready.tool_manager, "execute", _recording_execute)

    client.post(
        "/api/v1/voice/respond",
        json={"audio_base64": _audio_base64("hello"), "session_id": "s-voice-2"},
    )

    assert "tool.voice_speech_to_text" in calls
    assert "tool.voice_text_to_speech" not in calls


class TestVoiceSettings:
    """
    `GET`/`PUT /api/v1/voice/settings` -- the small, additive settings
    endpoint (Section 9/19) exposing the shared, current Voice
    language preference. Ordered to run last in this module so no
    earlier test's fixed `language=`/default-preference assumptions
    are disturbed by a preference change made here.
    """

    def test_get_settings_reports_configured_defaults(self, voice_ready, client) -> None:
        response = client.get("/api/v1/voice/settings")

        assert response.status_code == 200
        body = response.json()
        assert body["input_language"] == "auto"
        assert body["output_language"] == "follow_input"
        assert body["stt_available"] is True
        assert body["tts_available"] is True

    def test_put_settings_updates_input_language(self, voice_ready, client) -> None:
        response = client.put(
            "/api/v1/voice/settings", json={"input_language": "hi"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["input_language"] == "hi"
        # Untouched field is preserved, not reset to a hardcoded default.
        assert body["output_language"] == "follow_input"

        # A later GET observes the same, now-current preference.
        get_response = client.get("/api/v1/voice/settings")
        assert get_response.json()["input_language"] == "hi"

    def test_put_settings_updates_output_language_independently(
        self, voice_ready, client
    ) -> None:
        client.put("/api/v1/voice/settings", json={"input_language": "auto"})

        response = client.put(
            "/api/v1/voice/settings", json={"output_language": "en"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["output_language"] == "en"
        assert body["input_language"] == "auto"

    def test_put_settings_rejects_invalid_input_language(self, voice_ready, client) -> None:
        response = client.put(
            "/api/v1/voice/settings", json={"input_language": "fr"}
        )

        assert response.status_code == 422

    def test_put_settings_rejects_invalid_output_language(self, voice_ready, client) -> None:
        response = client.put(
            "/api/v1/voice/settings", json={"output_language": "auto"}
        )

        assert response.status_code == 422

        # Restore defaults so this class's mutations never leak into
        # any test defined after it in a future revision of this file.
        client.put(
            "/api/v1/voice/settings",
            json={"input_language": "auto", "output_language": "follow_input"},
        )
