"""
Unit tests for the STT/TTS engine adapters
(`faster_whisper_engine.py`/`piper_engine.py`), including the
"auto" device resolution's graceful CPU fallback (Section 14) and the
dependency-unavailable/initialization-failure error paths (Section 18)
-- exercised with fake injected `faster_whisper`/`piper` modules so
these behaviors are deterministically testable without the real,
heavy optional dependencies installed.
"""

from __future__ import annotations

import sys
import types

import pytest

from parika.providers.local_speech.engines import faster_whisper_engine, piper_engine
from parika.providers.local_speech.engines.piper_engine import PiperVoiceSpec
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
# Piper
# ----------------------------------------------------------------------


def test_piper_dependency_unavailable_raises_clean_error() -> None:
    assert piper_engine.piper_dependency_available() is False

    with pytest.raises(LocalSpeechEngineUnavailableError):
        piper_engine.PiperTtsEngine(model_path="/models/voice.onnx")


def test_piper_missing_model_path_raises_clean_error_even_if_installed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(piper_engine, "piper_dependency_available", lambda: True)

    with pytest.raises(LocalSpeechEngineUnavailableError):
        piper_engine.PiperTtsEngine(model_path="")


def test_piper_auto_device_falls_back_to_cpu(monkeypatch) -> None:
    monkeypatch.setattr(piper_engine, "piper_dependency_available", lambda: True)

    class _FakeVoice:
        def __init__(self, use_cuda: bool) -> None:
            self.use_cuda = use_cuda
            self.config = types.SimpleNamespace(sample_rate=22050)

        def synthesize_stream_raw(self, text, *, speaker_id, length_scale, noise_scale, noise_w):
            yield b"\x00\x01" * 5

    class _FakePiperVoice:
        @classmethod
        def load(cls, model_path, *, config_path, use_cuda):
            if use_cuda:
                raise RuntimeError("no CUDA device available")
            return _FakeVoice(use_cuda=use_cuda)

    fake_module = types.ModuleType("piper")
    fake_module.PiperVoice = _FakePiperVoice
    monkeypatch.setitem(sys.modules, "piper", fake_module)

    engine = piper_engine.PiperTtsEngine(model_path="/models/voice.onnx", device="auto")

    assert engine._voice.use_cuda is False  # noqa: SLF001 -- verifying fallback
    assert engine.sample_rate == 22050

    result = engine.synthesize("Hello there.")
    assert result.sample_rate == 22050
    assert result.pcm_bytes == b"\x00\x01" * 5


def test_piper_explicit_device_failure_is_not_silently_overridden(monkeypatch) -> None:
    monkeypatch.setattr(piper_engine, "piper_dependency_available", lambda: True)

    class _AlwaysFailingPiperVoice:
        @classmethod
        def load(cls, model_path, *, config_path, use_cuda):
            raise RuntimeError("cuda unavailable")

    fake_module = types.ModuleType("piper")
    fake_module.PiperVoice = _AlwaysFailingPiperVoice
    monkeypatch.setitem(sys.modules, "piper", fake_module)

    with pytest.raises(LocalSpeechEngineInitializationError):
        piper_engine.PiperTtsEngine(model_path="/models/voice.onnx", device="cuda")


def test_piper_rejects_empty_text(monkeypatch) -> None:
    monkeypatch.setattr(piper_engine, "piper_dependency_available", lambda: True)

    class _FakeVoice:
        config = types.SimpleNamespace(sample_rate=22050)

        def synthesize_stream_raw(self, *args, **kwargs):
            raise AssertionError("should not be called for empty text")

    class _FakePiperVoice:
        @classmethod
        def load(cls, model_path, *, config_path, use_cuda):
            return _FakeVoice()

    fake_module = types.ModuleType("piper")
    fake_module.PiperVoice = _FakePiperVoice
    monkeypatch.setitem(sys.modules, "piper", fake_module)

    engine = piper_engine.PiperTtsEngine(model_path="/models/voice.onnx")

    with pytest.raises(LocalSpeechExecutionError):
        engine.synthesize("   ")


def _fake_piper_module(*, sample_rate_by_path: dict) -> types.ModuleType:
    """
    A fake `piper` module whose `PiperVoice.load()` returns a distinct
    fake voice per `model_path`, each remembering which path/text it
    was asked to synthesize -- lets multi-voice tests assert exactly
    which underlying voice model was actually used.
    """

    class _FakeVoice:
        def __init__(self, model_path: str) -> None:
            self.model_path = model_path
            self.config = types.SimpleNamespace(
                sample_rate=sample_rate_by_path[model_path]
            )
            self.synthesized_with: list[tuple[str, int | None]] = []

        def synthesize_stream_raw(
            self, text, *, speaker_id, length_scale, noise_scale, noise_w
        ):
            self.synthesized_with.append((text, speaker_id))
            yield f"[{self.model_path}]".encode() + b"\x00\x01"

    class _FakePiperVoice:
        instances: dict[str, "_FakeVoice"] = {}

        @classmethod
        def load(cls, model_path, *, config_path, use_cuda):
            voice = _FakeVoice(model_path)
            cls.instances[model_path] = voice
            return voice

    fake_module = types.ModuleType("piper")
    fake_module.PiperVoice = _FakePiperVoice
    return fake_module


def test_piper_multi_voice_english_primary_used_by_default(monkeypatch) -> None:
    monkeypatch.setattr(piper_engine, "piper_dependency_available", lambda: True)
    fake_module = _fake_piper_module(
        sample_rate_by_path={
            "/models/en.onnx": 22050,
            "/models/hi.onnx": 22050,
        }
    )
    monkeypatch.setitem(sys.modules, "piper", fake_module)

    engine = piper_engine.PiperTtsEngine(
        model_path="/models/en.onnx",
        language="en",
        additional_voices={"hi": PiperVoiceSpec(model_path="/models/hi.onnx")},
    )

    result = engine.synthesize("Hello there.")
    assert result.pcm_bytes.startswith(b"[/models/en.onnx]")
    # The Hindi voice is never loaded until actually requested.
    assert "/models/hi.onnx" not in fake_module.PiperVoice.instances


def test_piper_multi_voice_selects_hindi_voice_when_requested(monkeypatch) -> None:
    monkeypatch.setattr(piper_engine, "piper_dependency_available", lambda: True)
    fake_module = _fake_piper_module(
        sample_rate_by_path={
            "/models/en.onnx": 22050,
            "/models/hi.onnx": 22050,
        }
    )
    monkeypatch.setitem(sys.modules, "piper", fake_module)

    engine = piper_engine.PiperTtsEngine(
        model_path="/models/en.onnx",
        language="en",
        additional_voices={"hi": PiperVoiceSpec(model_path="/models/hi.onnx")},
    )

    result = engine.synthesize("नमस्ते।", language="hi")
    assert result.pcm_bytes.startswith(b"[/models/hi.onnx]")


def test_piper_multi_voice_lazily_loads_additional_voice_only_once(monkeypatch) -> None:
    monkeypatch.setattr(piper_engine, "piper_dependency_available", lambda: True)
    fake_module = _fake_piper_module(
        sample_rate_by_path={
            "/models/en.onnx": 22050,
            "/models/hi.onnx": 22050,
        }
    )
    monkeypatch.setitem(sys.modules, "piper", fake_module)

    engine = piper_engine.PiperTtsEngine(
        model_path="/models/en.onnx",
        language="en",
        additional_voices={"hi": PiperVoiceSpec(model_path="/models/hi.onnx")},
    )

    engine.synthesize("Ek.", language="hi")
    engine.synthesize("Do.", language="hi")

    hindi_voice = fake_module.PiperVoice.instances["/models/hi.onnx"]
    assert len(hindi_voice.synthesized_with) == 2


def test_piper_multi_voice_unconfigured_language_falls_back_to_primary(
    monkeypatch,
) -> None:
    monkeypatch.setattr(piper_engine, "piper_dependency_available", lambda: True)
    fake_module = _fake_piper_module(sample_rate_by_path={"/models/en.onnx": 22050})
    monkeypatch.setitem(sys.modules, "piper", fake_module)

    engine = piper_engine.PiperTtsEngine(model_path="/models/en.onnx", language="en")

    # No Hindi voice was ever configured -- never fabricates support;
    # falls back to the primary (English) voice instead of raising.
    result = engine.synthesize("Hello.", language="hi")
    assert result.pcm_bytes.startswith(b"[/models/en.onnx]")
