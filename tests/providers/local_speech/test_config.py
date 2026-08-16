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
            "providers.local_speech.tts_engine": "piper",
            "providers.local_speech.tts_voice": "hi_IN-test-medium",
            "providers.local_speech.tts_model_path": "/models/piper/voice.onnx",
            "providers.local_speech.tts_config_path": "/models/piper/voice.json",
            "providers.local_speech.tts_device": "cuda",
            "providers.local_speech.tts_sample_rate": 24000,
            "providers.local_speech.tts_speaker_id": 2,
            "providers.local_speech.tts_length_scale": 1.2,
            "providers.local_speech.tts_noise_scale": 0.5,
            "providers.local_speech.tts_noise_w": 0.9,
            "providers.local_speech.tts_hindi_voice": "hi_IN-priyamvada-medium",
            "providers.local_speech.tts_hindi_model_path": "/models/piper/hindi.onnx",
            "providers.local_speech.tts_hindi_config_path": "/models/piper/hindi.json",
            "providers.local_speech.tts_hindi_speaker_id": 1,
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
    assert config.tts_voice == "hi_IN-test-medium"
    assert config.tts_model_path == "/models/piper/voice.onnx"
    assert config.tts_config_path == "/models/piper/voice.json"
    assert config.tts_device == "cuda"
    assert config.tts_sample_rate == 24000
    assert config.tts_speaker_id == 2
    assert config.tts_length_scale == 1.2
    assert config.tts_noise_scale == 0.5
    assert config.tts_noise_w == 0.9
    assert config.tts_hindi_voice == "hi_IN-priyamvada-medium"
    assert config.tts_hindi_model_path == "/models/piper/hindi.onnx"
    assert config.tts_hindi_config_path == "/models/piper/hindi.json"
    assert config.tts_hindi_speaker_id == 1


def test_hindi_voice_fields_default_to_unconfigured() -> None:
    config = load_local_speech_config(None)

    assert config.tts_hindi_model_path == ""
    assert config.tts_hindi_config_path == ""
    assert config.tts_hindi_speaker_id is None
    assert config.tts_hindi_voice == "hi_IN-priyamvada-medium"


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
