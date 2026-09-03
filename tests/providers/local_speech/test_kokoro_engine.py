"""
Unit tests for the Kokoro TTS engine adapter
(`kokoro_engine.py`), including the dependency-unavailable/
initialization-failure error paths and language mapping -- exercised
with a fake injected `kokoro_onnx` module so these behaviors are
deterministically testable without the real, heavy optional dependency
installed.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from parika.providers.local_speech.engines import kokoro_engine
from parika.providers.local_speech.exceptions import (
    LocalSpeechEngineInitializationError,
    LocalSpeechEngineUnavailableError,
    LocalSpeechExecutionError,
)


def test_kokoro_dependency_unavailable_raises_clean_error(monkeypatch) -> None:
    # Since kokoro-onnx is installed in the test environment, we need to
    # mock the dependency check to simulate it being unavailable.
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: False)

    with pytest.raises(LocalSpeechEngineUnavailableError):
        kokoro_engine.KokoroTtsEngine(
            model_path="/models/kokoro.onnx", voices_path="/models/voices.bin"
        )


def test_kokoro_missing_model_path_raises_clean_error_even_if_installed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    with pytest.raises(LocalSpeechEngineUnavailableError):
        kokoro_engine.KokoroTtsEngine(model_path="", voices_path="/models/voices.bin")


def test_kokoro_missing_voices_path_raises_clean_error_even_if_installed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    with pytest.raises(LocalSpeechEngineUnavailableError):
        kokoro_engine.KokoroTtsEngine(
            model_path="/models/kokoro.onnx", voices_path=""
        )


def _fake_kokoro_module(
    *,
    available_voices: list[str] | None = None,
    sample_rate: int = 24000,
    fail_load: bool = False,
) -> types.ModuleType:
    """
    A fake `kokoro_onnx` module whose `Kokoro` class can be configured
    for different test scenarios.
    """

    class _FakeKokoro:
        def __init__(self, model_path: str, voices_path: str, **kwargs):
            self.model_path = model_path
            self.voices_path = voices_path
            if fail_load:
                raise RuntimeError("failed to load model")

        def get_voices(self) -> list[str]:
            return available_voices or ["hf_beta", "hf_alpha"]

        def create(
            self,
            text: str,
            voice: str,
            speed: float = 1.0,
            lang: str = "en-us",
            **kwargs,
        ) -> tuple[np.ndarray, int]:
            # Return float32 audio data (simulating 1 second of silence at sample_rate)
            audio = np.zeros(sample_rate, dtype=np.float32)
            return audio, sample_rate

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    return fake_module


def test_kokoro_loads_successfully_with_valid_voice(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)
    fake_module = _fake_kokoro_module()
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx",
        voices_path="/models/voices.bin",
        voice_name="hf_beta",
    )

    assert engine.sample_rate == 24000


def test_kokoro_rejects_unknown_voice(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)
    fake_module = _fake_kokoro_module(available_voices=["hf_alpha"])
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    with pytest.raises(LocalSpeechEngineInitializationError) as exc_info:
        kokoro_engine.KokoroTtsEngine(
            model_path="/models/kokoro.onnx",
            voices_path="/models/voices.bin",
            voice_name="hf_beta",
        )

    assert "not found in available voices" in str(exc_info.value)


def test_kokoro_initialization_failure_raises_clean_error(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)
    fake_module = _fake_kokoro_module(fail_load=True)
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    with pytest.raises(LocalSpeechEngineInitializationError):
        kokoro_engine.KokoroTtsEngine(
            model_path="/models/kokoro.onnx", voices_path="/models/voices.bin"
        )


def test_kokoro_rejects_empty_text(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)
    fake_module = _fake_kokoro_module()
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx", voices_path="/models/voices.bin"
    )

    with pytest.raises(LocalSpeechExecutionError):
        engine.synthesize("   ")


def test_kokoro_synthesize_returns_pcm_bytes_and_sample_rate(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)
    fake_module = _fake_kokoro_module(sample_rate=24000)
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx", voices_path="/models/voices.bin"
    )

    result = engine.synthesize("Hello world.")

    assert result.sample_rate == 24000
    assert isinstance(result.pcm_bytes, bytes)
    # Should be int16 PCM: 1 second * 24000 samples * 2 bytes = 48000 bytes
    assert len(result.pcm_bytes) == 24000 * 2


def test_kokoro_language_mapping_hi(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    captured_lang: dict[str, str] = {}

    class _FakeKokoro:
        def __init__(self, model_path: str, voices_path: str, **kwargs):
            pass

        def get_voices(self) -> list[str]:
            return ["hf_beta"]

        def create(
            self,
            text: str,
            voice: str,
            speed: float = 1.0,
            lang: str = "en-us",
            **kwargs,
        ) -> tuple[np.ndarray, int]:
            captured_lang["lang"] = lang
            audio = np.zeros(24000, dtype=np.float32)
            return audio, 24000

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx", voices_path="/models/voices.bin"
    )
    engine.synthesize("नमस्ते", language="hi")

    assert captured_lang["lang"] == "hi"


def test_kokoro_language_mapping_en(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    captured_lang: dict[str, str] = {}

    class _FakeKokoro:
        def __init__(self, model_path: str, voices_path: str, **kwargs):
            pass

        def get_voices(self) -> list[str]:
            return ["hf_beta"]

        def create(
            self,
            text: str,
            voice: str,
            speed: float = 1.0,
            lang: str = "en-us",
            **kwargs,
        ) -> tuple[np.ndarray, int]:
            captured_lang["lang"] = lang
            audio = np.zeros(24000, dtype=np.float32)
            return audio, 24000

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx", voices_path="/models/voices.bin"
    )
    engine.synthesize("Hello", language="en")

    assert captured_lang["lang"] == "en-us"


def test_kokoro_language_mapping_en_us(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    captured_lang: dict[str, str] = {}

    class _FakeKokoro:
        def __init__(self, model_path: str, voices_path: str, **kwargs):
            pass

        def get_voices(self) -> list[str]:
            return ["hf_beta"]

        def create(
            self,
            text: str,
            voice: str,
            speed: float = 1.0,
            lang: str = "en-us",
            **kwargs,
        ) -> tuple[np.ndarray, int]:
            captured_lang["lang"] = lang
            audio = np.zeros(24000, dtype=np.float32)
            return audio, 24000

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx", voices_path="/models/voices.bin"
    )
    engine.synthesize("Hello", language="en-us")

    assert captured_lang["lang"] == "en-us"


def test_kokoro_language_mapping_unknown_fallbacks_to_en_us(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    captured_lang: dict[str, str] = {}

    class _FakeKokoro:
        def __init__(self, model_path: str, voices_path: str, **kwargs):
            pass

        def get_voices(self) -> list[str]:
            return ["hf_beta"]

        def create(
            self,
            text: str,
            voice: str,
            speed: float = 1.0,
            lang: str = "en-us",
            **kwargs,
        ) -> tuple[np.ndarray, int]:
            captured_lang["lang"] = lang
            audio = np.zeros(24000, dtype=np.float32)
            return audio, 24000

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx", voices_path="/models/voices.bin"
    )
    engine.synthesize("Hello", language="fr")

    assert captured_lang["lang"] == "en-us"


def test_kokoro_language_none_uses_default(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    captured_lang: dict[str, str] = {}

    class _FakeKokoro:
        def __init__(self, model_path: str, voices_path: str, **kwargs):
            pass

        def get_voices(self) -> list[str]:
            return ["hf_beta"]

        def create(
            self,
            text: str,
            voice: str,
            speed: float = 1.0,
            lang: str = "en-us",
            **kwargs,
        ) -> tuple[np.ndarray, int]:
            captured_lang["lang"] = lang
            audio = np.zeros(24000, dtype=np.float32)
            return audio, 24000

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx",
        voices_path="/models/voices.bin",
        language="en",
    )
    engine.synthesize("Hello", language=None)

    assert captured_lang["lang"] == "en-us"


def test_kokoro_voice_override(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    captured_voice: dict[str, str] = {}

    class _FakeKokoro:
        def __init__(self, model_path: str, voices_path: str, **kwargs):
            pass

        def get_voices(self) -> list[str]:
            return ["hf_beta", "hf_alpha"]

        def create(
            self,
            text: str,
            voice: str,
            speed: float = 1.0,
            lang: str = "en-us",
            **kwargs,
        ) -> tuple[np.ndarray, int]:
            captured_voice["voice"] = voice
            audio = np.zeros(24000, dtype=np.float32)
            return audio, 24000

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx",
        voices_path="/models/voices.bin",
        voice_name="hf_beta",
    )
    engine.synthesize("Hello", voice="hf_alpha")

    assert captured_voice["voice"] == "hf_alpha"


def test_kokoro_speed_parameter(monkeypatch) -> None:
    monkeypatch.setattr(kokoro_engine, "kokoro_dependency_available", lambda: True)

    captured_speed: dict[str, float] = {}

    class _FakeKokoro:
        def __init__(self, model_path: str, voices_path: str, **kwargs):
            pass

        def get_voices(self) -> list[str]:
            return ["hf_beta"]

        def create(
            self,
            text: str,
            voice: str,
            speed: float = 1.0,
            lang: str = "en-us",
            **kwargs,
        ) -> tuple[np.ndarray, int]:
            captured_speed["speed"] = speed
            audio = np.zeros(24000, dtype=np.float32)
            return audio, 24000

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = _FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_module)

    engine = kokoro_engine.KokoroTtsEngine(
        model_path="/models/kokoro.onnx",
        voices_path="/models/voices.bin",
        speed=1.5,
    )
    engine.synthesize("Hello")

    assert captured_speed["speed"] == 1.5