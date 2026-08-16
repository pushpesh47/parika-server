"""
Unit tests for `parika.providers.local_speech.driver.LocalSpeechProviderDriver`.
"""

from __future__ import annotations

import base64

import pytest

from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.speech_request import SpeechOperation, SpeechRequest
from parika.providers.local_speech.config import LocalSpeechProviderConfig
from parika.providers.local_speech.driver import LocalSpeechProviderDriver
from parika.providers.local_speech.engines.stt_engine import SttEngineResult
from parika.providers.local_speech.engines.tts_engine import TtsEngineResult
from parika.providers.local_speech.exceptions import (
    LocalSpeechEngineUnavailableError,
    LocalSpeechRequestError,
)


class _FakeSttEngine:
    def transcribe(self, audio_bytes, *, language=None):
        return SttEngineResult(
            text=f"transcribed:{audio_bytes.decode()}",
            language_detected=language or "en",
            duration_seconds=2.0,
            language_probability=0.87 if language is None else None,
        )


class _FakeTtsEngine:
    def __init__(self) -> None:
        self.requested_languages: list[str | None] = []

    def synthesize(self, text, *, voice=None, language=None):
        self.requested_languages.append(language)
        return TtsEngineResult(pcm_bytes=b"\x00\x01" * 10, sample_rate=16000)


def test_discover_models_is_empty_without_any_engine_installed(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )

    assert driver.discover_models() == ()


def test_check_health_reports_unavailable_without_any_engine_installed(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )

    health = driver.check_health()

    assert health.available is False


def test_execute_rejects_non_speech_request(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    model = ProviderModel(id="local_speech_stt", name="fake")

    with pytest.raises(LocalSpeechRequestError):
        driver.execute(model, object())  # type: ignore[arg-type]


def test_transcribe_uses_injected_stt_engine(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    driver._stt_engine = _FakeSttEngine()  # noqa: SLF001 -- test seam

    model = ProviderModel(id="local_speech_stt", name="fake")
    audio_base64 = base64.b64encode(b"hello").decode("ascii")

    result = driver.execute(
        model,
        SpeechRequest(
            operation=SpeechOperation.SPEECH_TO_TEXT,
            audio_base64=audio_base64,
        ),
    )

    assert result.text == "transcribed:hello"
    assert result.language_detected == "en"
    assert result.model_id == "local_speech_stt"
    assert result.language_confidence == 0.87


def test_transcribe_auto_sentinel_is_equivalent_to_no_language_hint(logger) -> None:
    """
    The Voice Module's explicit "auto" sentinel (see
    `parika.modules.voice.language`) must resolve to the same
    `language=None` engine call as simply omitting a language hint.
    """

    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    driver._stt_engine = _FakeSttEngine()  # noqa: SLF001 -- test seam

    model = ProviderModel(id="local_speech_stt", name="fake")
    audio_base64 = base64.b64encode(b"hello").decode("ascii")

    result = driver.execute(
        model,
        SpeechRequest(
            operation=SpeechOperation.SPEECH_TO_TEXT,
            audio_base64=audio_base64,
            language="auto",
        ),
    )

    # _FakeSttEngine defaults language_detected to "en" only when it
    # actually received language=None.
    assert result.language_detected == "en"
    assert result.language_confidence == 0.87


def test_synthesize_passes_through_language_to_engine(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    fake_engine = _FakeTtsEngine()
    driver._tts_engine = fake_engine  # noqa: SLF001 -- test seam

    model = ProviderModel(id="local_speech_tts", name="fake")

    driver.execute(
        model,
        SpeechRequest(
            operation=SpeechOperation.TEXT_TO_SPEECH, text="Hello.", language="hi"
        ),
    )

    assert fake_engine.requested_languages == ["hi"]


def test_transcribe_falls_back_to_configured_default_language(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(stt_default_language="hi"), logger=logger
    )
    driver._stt_engine = _FakeSttEngine()  # noqa: SLF001 -- test seam

    model = ProviderModel(id="local_speech_stt", name="fake")
    audio_base64 = base64.b64encode(b"hello").decode("ascii")

    result = driver.execute(
        model,
        SpeechRequest(operation=SpeechOperation.SPEECH_TO_TEXT, audio_base64=audio_base64),
    )

    assert result.language_detected == "hi"


def test_transcribe_requires_audio(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    driver._stt_engine = _FakeSttEngine()  # noqa: SLF001 -- test seam
    model = ProviderModel(id="local_speech_stt", name="fake")

    with pytest.raises(LocalSpeechRequestError):
        driver.execute(
            model, SpeechRequest(operation=SpeechOperation.SPEECH_TO_TEXT)
        )


def test_synthesize_uses_injected_tts_engine_and_produces_wav(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    driver._tts_engine = _FakeTtsEngine()  # noqa: SLF001 -- test seam

    model = ProviderModel(id="local_speech_tts", name="fake")

    result = driver.execute(
        model,
        SpeechRequest(operation=SpeechOperation.TEXT_TO_SPEECH, text="Hello there."),
    )

    assert result.audio_mime_type == "audio/wav"
    assert result.sample_rate == 16000
    assert result.audio_base64
    # A real WAV header ("RIFF"/"WAVE") is present -- proves this is a
    # self-describing file, not bare PCM.
    wav_bytes = base64.b64decode(result.audio_base64)
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"


def test_synthesize_requires_non_empty_text(logger) -> None:
    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    driver._tts_engine = _FakeTtsEngine()  # noqa: SLF001 -- test seam
    model = ProviderModel(id="local_speech_tts", name="fake")

    with pytest.raises(LocalSpeechRequestError):
        driver.execute(
            model, SpeechRequest(operation=SpeechOperation.TEXT_TO_SPEECH, text="   ")
        )


def test_stt_engine_construction_fails_gracefully_without_dependency(logger) -> None:
    """
    `faster-whisper` is not installed in this environment -- lazily
    constructing the real engine must raise a clean, typed exception
    rather than an ImportError leaking through.
    """

    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    model = ProviderModel(id="local_speech_stt", name="fake")
    audio_base64 = base64.b64encode(b"hello").decode("ascii")

    with pytest.raises(LocalSpeechEngineUnavailableError):
        driver.execute(
            model,
            SpeechRequest(
                operation=SpeechOperation.SPEECH_TO_TEXT, audio_base64=audio_base64
            ),
        )


def test_tts_engine_construction_fails_gracefully_without_dependency(logger) -> None:
    """
    `piper-tts` is not installed in this environment -- lazily
    constructing the real engine must raise a clean, typed exception
    rather than an ImportError leaking through.
    """

    driver = LocalSpeechProviderDriver(
        config=LocalSpeechProviderConfig(), logger=logger
    )
    model = ProviderModel(id="local_speech_tts", name="fake")

    with pytest.raises(LocalSpeechEngineUnavailableError):
        driver.execute(
            model,
            SpeechRequest(operation=SpeechOperation.TEXT_TO_SPEECH, text="Hello."),
        )
