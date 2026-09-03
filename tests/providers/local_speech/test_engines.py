"""
Unit tests for the STT/TTS engine adapters
(`faster_whisper_engine.py`/`kokoro_engine.py`), including the
"auto" device resolution's graceful CPU fallback (Section 14) and the
dependency-unavailable/initialization-failure error paths (Section 18)
-- exercised with fake injected `faster_whisper`/`kokoro_onnx` modules so
these behaviors are deterministically testable without the real,
heavy optional dependencies installed.
"""

from __future__ import annotations

import sys
import types

import pytest

from parika.providers.local_speech.engines import faster_whisper_engine, kokoro_engine
from parika.providers.local_speech.exceptions import (
    LocalSpeechEngineInitializationError,
    LocalSpeechEngineUnavailableError,
    LocalSpeechExecutionError,
    LocalSpeechRequestError,
)

# ----------------------------------------------------------------------
# faster-whisper
# ----------------------------------------------------------------------


def test_faster_whisper_dependency_unavailable_raises_clean_error() -> None:
    assert faster_whisper_engine.faster_whisper_dependency_available() is False

    with pytest.raises(LocalSpeechEngineUnavailableError):
        faster_whisper_engine.FasterWhisperSttEngine(model_size="tiny")


def test_faster_whisper_auto_device_falls_back_to_cpu(monkeypatch) -> None:
    monkeypatch.setattr(
        faster_whisper_engine, "faster_whisper_dependency_available", lambda: True
    )

    class _FakeWhisperModel:
        def __init__(self, model_size, *, device, compute_type, download_root):
            if device == "cuda":
                raise RuntimeError("no CUDA device available")
            self.model_size = model_size
            self.device = device

        def transcribe(self, audio, *, language, beam_size):
            segment = types.SimpleNamespace(text="hello world")
            info = types.SimpleNamespace(language="en", duration=1.0)
            return [segment], info

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    engine = faster_whisper_engine.FasterWhisperSttEngine(
        model_size="small", device="auto"
    )

    assert engine._model.device == "cpu"  # noqa: SLF001 -- verifying fallback

    result = engine.transcribe(b"fake-audio-bytes")
    assert result.text == "hello world"
    assert result.language_detected == "en"
    assert result.duration_seconds == 1.0


def test_faster_whisper_explicit_device_failure_is_not_silently_overridden(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        faster_whisper_engine, "faster_whisper_dependency_available", lambda: True
    )

    class _AlwaysFailingWhisperModel:
        def __init__(self, model_size, *, device, compute_type, download_root):
            raise RuntimeError(f"device '{device}' unavailable")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _AlwaysFailingWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    with pytest.raises(LocalSpeechEngineInitializationError):
        faster_whisper_engine.FasterWhisperSttEngine(model_size="small", device="cuda")


def test_faster_whisper_captures_language_probability_in_auto_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        faster_whisper_engine, "faster_whisper_dependency_available", lambda: True
    )

    class _FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, *, language, beam_size):
            segment = types.SimpleNamespace(text="namaste")
            info = types.SimpleNamespace(
                language="hi", duration=1.2, language_probability=0.97
            )
            return [segment], info

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    engine = faster_whisper_engine.FasterWhisperSttEngine(model_size="small")

    result = engine.transcribe(b"fake-audio-bytes")
    assert result.language_detected == "hi"
    assert result.language_probability == 0.97


def test_faster_whisper_omits_probability_when_engine_does_not_report_one(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        faster_whisper_engine, "faster_whisper_dependency_available", lambda: True
    )

    class _FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, *, language, beam_size):
            segment = types.SimpleNamespace(text="hello")
            info = types.SimpleNamespace(language="en", duration=1.0)
            return [segment], info

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    engine = faster_whisper_engine.FasterWhisperSttEngine(model_size="small")

    result = engine.transcribe(b"fake-audio-bytes", language="en")
    assert result.language_probability is None


def test_faster_whisper_english_only_model_rejects_hindi_request(monkeypatch) -> None:
    monkeypatch.setattr(
        faster_whisper_engine, "faster_whisper_dependency_available", lambda: True
    )

    class _FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            raise AssertionError("should not be called for a rejected request")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    engine = faster_whisper_engine.FasterWhisperSttEngine(model_size="small.en")

    with pytest.raises(LocalSpeechRequestError):
        engine.transcribe(b"fake-audio-bytes", language="hi")


def test_faster_whisper_rejects_empty_audio(monkeypatch) -> None:
    monkeypatch.setattr(
        faster_whisper_engine, "faster_whisper_dependency_available", lambda: True
    )

    class _FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            raise AssertionError("should not be called for empty audio")

    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    engine = faster_whisper_engine.FasterWhisperSttEngine(model_size="small")

    with pytest.raises(LocalSpeechExecutionError):
        engine.transcribe(b"")

# ----------------------------------------------------------------------
# Kokoro
# ----------------------------------------------------------------------


def test_kokoro_dependency_unavailable_raises_clean_error() -> None:
    assert kokoro_engine.kokoro_dependency_available() is False

    with pytest.raises(LocalSpeechEngineUnavailableError):
        kokoro_engine.KokoroTtsEngine(
            model_path="/models/kokoro-v1.0.onnx",
            voices_path="/models/voices-v1.0.bin",
        )


def test_kokoro_missing_model_path_raises_clean_error_even_if_installed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    with pytest.raises(LocalSpeechEngineUnavailableError):
        kokoro_engine.KokoroTtsEngine(model_path="", voices_path="/models/voices.bin")

    with pytest.raises(LocalSpeechEngineUnavailableError):
        kokoro_engine.KokoroTtsEngine(
            model_path="/models/kokoro-v1.0.onnx", voices_path=""
        )


def test_kokoro_rejects_empty_text(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    class _FakeKokoro:
        def __init__(self, model_path, voices_path):
            pass

        def get_voices(self):
            return {"hf_beta"}

        def create(self, text, *, voice, speed, lang):
            raise AssertionError("should not be called for empty text")

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro-v1.0.onnx", voices_path="/models/voices-v1.0.bin"
    )

    with pytest.raises(LocalSpeechExecutionError):
        engine.synthesize("   ")


def test_kokoro_unknown_voice_raises_clean_error(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    class _FakeKokoro:
        def __init__(self, model_path, voices_path):
            pass

        def get_voices(self):
            return {"hf_beta"}

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    with pytest.raises(LocalSpeechEngineInitializationError):
        kokoro_engine.KokoroTtsEngine(
            model_path="/models/kokoro-v1.0.onnx",
            voices_path="/models/voices-v1.0.bin",
            voice_name="unknown_voice",
        )


def test_kokoro_synthesize_returns_pcm_and_sample_rate(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    import numpy as np

    class _FakeKokoro:
        def __init__(self, model_path, voices_path):
            pass

        def get_voices(self):
            return {"hf_beta"}

        def create(self, text, *, voice, speed, lang):
            # Return float32 audio array and sample rate
            audio = np.array([0.5, -0.5, 0.25], dtype=np.float32)
            return audio, 24000

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro-v1.0.onnx", voices_path="/models/voices-v1.0.bin"
    )

    result = engine.synthesize("Hello there.")

    assert result.sample_rate == 24000
    assert len(result.pcm_bytes) == 6  # 3 samples * 2 bytes per int16
    # Verify it's int16 little-endian
    assert result.pcm_bytes[:2] == (int(0.5 * 32767)).to_bytes(2, "little", signed=True)