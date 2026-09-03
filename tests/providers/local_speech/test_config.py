"""
Unit tests for `parika.providers.local_speech.config`.
"""

from __future__ import annotations

from parika.providers.local_speech.config import (
    LocalSpeechProviderConfig,
    load_local_speech_config,
)


class _FakeConfiguration:
    def __init__(self, values: dict) -> None:
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


def test_none_configuration_returns_dataclass_defaults() -> None:
    config = load_local_speech_config(None)

    assert config == LocalSpeechProviderConfig()


def test_reads_every_configured_field() -> None:
    configuration = _FakeConfiguration(
        {
            "providers.local_speech.enabled": False,
            "providers.local_speech.stt_engine": "faster_whisper",
            "providers.local_speech.stt_model_size": "medium",
            "providers.local_speech.stt_device": "cpu",
            "providers.local_speech.stt_compute_type": "int8",
            "providers.local_speech.stt_default_language": "hi",
            "providers.local_speech.stt_model_directory": "/models/whisper",
            "providers.local_speech.stt_beam_size": 3,
            "providers.local_speech.tts_kokoro_voice": "hf_beta",
            "providers.local_speech.tts_kokoro_model_path": "/models/kokoro/model.onnx",
            "providers.local_speech.tts_kokoro_voices_path": "/models/kokoro/voices.bin",
            "providers.local_speech.tts_kokoro_speed": 1.5,
        }
    )

    config = load_local_speech_config(configuration)

    assert config.enabled is False
    assert config.stt_model_size == "medium"
    assert config.stt_device == "cpu"
    assert config.stt_compute_type == "int8"
    assert config.stt_default_language == "hi"
    assert config.stt_model_directory == "/models/whisper"
    assert config.stt_beam_size == 3
    assert config.tts_kokoro_voice == "hf_beta"
    assert config.tts_kokoro_model_path == "/models/kokoro/model.onnx"
    assert config.tts_kokoro_voices_path == "/models/kokoro/voices.bin"
    assert config.tts_kokoro_speed == 1.5


def test_empty_string_language_and_directory_normalize_to_none() -> None:
    configuration = _FakeConfiguration(
        {
            "providers.local_speech.stt_default_language": "",
            "providers.local_speech.stt_model_directory": "",
        }
    )

    config = load_local_speech_config(configuration)

    assert config.stt_default_language is None
    assert config.stt_model_directory is None