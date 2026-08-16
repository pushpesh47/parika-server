"""
Unit tests for `parika.providers.local_speech.discovery`.

Mirrors `tests/providers/comfyui/test_discovery.py`'s "installed
environment is authoritative" testing shape: a model is only ever
offered when its dependency/model file is actually present.
"""

from __future__ import annotations

from parika.providers.local_speech import discovery
from parika.providers.local_speech.config import LocalSpeechProviderConfig


def test_neither_engine_available_discovers_nothing(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "faster_whisper_dependency_available", lambda: False)
    monkeypatch.setattr(discovery, "piper_dependency_available", lambda: False)

    models = discovery.discover_models(config=LocalSpeechProviderConfig())

    assert models == ()


def test_stt_offered_when_faster_whisper_dependency_available(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "faster_whisper_dependency_available", lambda: True)
    monkeypatch.setattr(discovery, "piper_dependency_available", lambda: False)

    models = discovery.discover_models(config=LocalSpeechProviderConfig())

    assert len(models) == 1
    assert models[0].id == discovery.STT_MODEL_ID


def test_tts_offered_only_when_dependency_and_model_file_are_both_present(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(discovery, "faster_whisper_dependency_available", lambda: False)
    monkeypatch.setattr(discovery, "piper_dependency_available", lambda: True)

    # Dependency available but no configured model file -> still not offered.
    models = discovery.discover_models(
        config=LocalSpeechProviderConfig(tts_model_path="")
    )
    assert models == ()

    # Dependency available, configured model file does not exist -> not offered.
    missing_path = str(tmp_path / "missing-voice.onnx")
    models = discovery.discover_models(
        config=LocalSpeechProviderConfig(tts_model_path=missing_path)
    )
    assert models == ()

    # Dependency available and the configured model file exists -> offered.
    voice_path = tmp_path / "voice.onnx"
    voice_path.write_bytes(b"fake-onnx-model")
    models = discovery.discover_models(
        config=LocalSpeechProviderConfig(tts_model_path=str(voice_path))
    )

    assert len(models) == 1
    assert models[0].id == discovery.TTS_MODEL_ID


def test_tts_offered_when_only_hindi_voice_is_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(discovery, "faster_whisper_dependency_available", lambda: False)
    monkeypatch.setattr(discovery, "piper_dependency_available", lambda: True)

    hindi_voice_path = tmp_path / "hindi.onnx"
    hindi_voice_path.write_bytes(b"fake-onnx-model")

    # English slot unset -- Hindi-only is still independently offered.
    models = discovery.discover_models(
        config=LocalSpeechProviderConfig(
            tts_model_path="", tts_hindi_model_path=str(hindi_voice_path)
        )
    )

    assert len(models) == 1
    assert models[0].id == discovery.TTS_MODEL_ID
    assert "hi:" in models[0].name
    assert "en:" not in models[0].name


def test_tts_name_lists_both_languages_when_both_are_configured(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(discovery, "faster_whisper_dependency_available", lambda: False)
    monkeypatch.setattr(discovery, "piper_dependency_available", lambda: True)

    english_voice_path = tmp_path / "english.onnx"
    english_voice_path.write_bytes(b"fake-onnx-model")
    hindi_voice_path = tmp_path / "hindi.onnx"
    hindi_voice_path.write_bytes(b"fake-onnx-model")

    models = discovery.discover_models(
        config=LocalSpeechProviderConfig(
            tts_model_path=str(english_voice_path),
            tts_hindi_model_path=str(hindi_voice_path),
        )
    )

    assert len(models) == 1
    assert "en:" in models[0].name
    assert "hi:" in models[0].name


def test_both_engines_available_discovers_both_models(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(discovery, "faster_whisper_dependency_available", lambda: True)
    monkeypatch.setattr(discovery, "piper_dependency_available", lambda: True)

    voice_path = tmp_path / "voice.onnx"
    voice_path.write_bytes(b"fake-onnx-model")

    models = discovery.discover_models(
        config=LocalSpeechProviderConfig(tts_model_path=str(voice_path))
    )

    model_ids = {model.id for model in models}
    assert model_ids == {discovery.STT_MODEL_ID, discovery.TTS_MODEL_ID}
