"""
Unit tests for `parika.interfaces.runtime`.

Ollama connectivity is faked via a small `OllamaTransport` double so
these tests never depend on a real Ollama installation, while every
other Core component wired by `build_default_runtime()` is real.
"""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.module_manager.state import ModuleState
from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.modules.chat.driver import CHAT_CAPABILITY_ID
from parika.providers.ollama.exceptions import OllamaConnectionError
from parika.providers.ollama.manifest import OLLAMA_PROVIDER_ID
from parika.tools.web_search.manifest import WEB_SEARCH_CAPABILITY_ID


class _FakeOllamaTransport:
    def __init__(self, *, models: list[dict[str, Any]] | None = None) -> None:
        self._models = models if models is not None else []
        self.calls: list[str] = []
        self.chat_calls: list[Mapping[str, Any]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        self.calls.append(url)

        if url.endswith("/api/tags"):
            return {"models": self._models}

        if url.endswith("/api/show"):
            return {"capabilities": ["completion"]}

        if url.endswith("/api/version"):
            return {"version": "0.0.0-test"}

        if url.endswith("/api/chat"):
            self.chat_calls.append(payload or {})
            return {"message": {"role": "assistant", "content": "pong"}, "done": True}

        return {}

    def stream_lines(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> Iterator[dict[str, Any]]:
        self.calls.append(url)
        return iter(())


class _FailingOllamaTransport:
    """Simulates Ollama not being installed/running at all."""

    def request_json(self, *args: object, **kwargs: object) -> dict[str, Any]:
        raise OllamaConnectionError("connection refused")

    def stream_lines(self, *args: object, **kwargs: object):
        raise OllamaConnectionError("connection refused")
        yield {}  # pragma: no cover - unreachable, satisfies generator typing


class TestBuildDefaultRuntime:
    def test_registers_every_builtin_module(self, tmp_path) -> None:
        runtime = build_default_runtime(
            ollama_transport=_FakeOllamaTransport(),
            data_directory=tmp_path / "data",
        )

        module_ids = {module.id for module in runtime.module_manager.get_all()}
        assert module_ids == {
            "web_search",
            "runtime_info",
            "filesystem",
            "shell",
            "weather",
            "currency",
            "news",
            "expense",
            "chat",
            "knowledge_indexing",
            "experience",
            "coding",
            "repository_intelligence",
            "coding_agent",
            "memory",
            "ocr",
            "vision",
            "document",
            "video",
            "generation",
            "voice",
            "media",
        }
        assert all(
            module.state is ModuleState.ACTIVE
            for module in runtime.module_manager.get_all()
        )

        shutdown_runtime(runtime)

    def test_registers_capabilities_from_both_modules(self, tmp_path) -> None:
        runtime = build_default_runtime(
            ollama_transport=_FakeOllamaTransport(),
            data_directory=tmp_path / "data",
        )

        assert runtime.capability_registry.contains(WEB_SEARCH_CAPABILITY_ID)
        assert runtime.capability_registry.contains(CHAT_CAPABILITY_ID)

        chat_definition = runtime.capability_registry.get(CHAT_CAPABILITY_ID)
        assert chat_definition.category is CapabilityCategory.LLM

        shutdown_runtime(runtime)

    def test_registers_and_discovers_ollama_provider(self, tmp_path) -> None:
        runtime = build_default_runtime(
            ollama_transport=_FakeOllamaTransport(
                models=[{"name": "qwen3:8b"}]
            ),
            data_directory=tmp_path / "data",
        )

        provider = runtime.provider_manager.get(OLLAMA_PROVIDER_ID)
        assert provider.enabled is True
        assert len(provider.models) == 1
        assert provider.health is not None
        assert provider.health.available is True

        shutdown_runtime(runtime)

    def test_survives_ollama_being_unreachable(self, tmp_path) -> None:
        # Must not raise even though every Ollama call fails.
        runtime = build_default_runtime(
            ollama_transport=_FailingOllamaTransport(),
            data_directory=tmp_path / "data",
        )

        provider = runtime.provider_manager.get(OLLAMA_PROVIDER_ID)
        assert provider.models == frozenset()
        assert provider.health is None

        # The rest of PARIKA (e.g. the Web Search capability) is
        # still fully available.
        assert runtime.capability_registry.contains(WEB_SEARCH_CAPABILITY_ID)

        shutdown_runtime(runtime)

    def test_skips_ollama_discovery_when_disabled(self, tmp_path) -> None:
        transport = _FakeOllamaTransport(models=[{"name": "qwen3:8b"}])

        runtime = build_default_runtime(
            ollama_transport=transport,
            discover_ollama_models=False,
            data_directory=tmp_path / "data",
        )

        assert transport.calls == []
        provider = runtime.provider_manager.get(OLLAMA_PROVIDER_ID)
        assert provider.models == frozenset()

        shutdown_runtime(runtime)

    def test_load_modules_false_registers_without_activating(self, tmp_path) -> None:
        runtime = build_default_runtime(
            ollama_transport=_FakeOllamaTransport(),
            load_modules=False,
            data_directory=tmp_path / "data",
        )

        assert all(
            module.state is ModuleState.INACTIVE
            for module in runtime.module_manager.get_all()
        )
        assert not runtime.capability_registry.contains(
            WEB_SEARCH_CAPABILITY_ID
        )

    def test_service_container_exposes_brain(self, tmp_path) -> None:
        from parika.core.brain.brain import Brain

        runtime = build_default_runtime(
            ollama_transport=_FakeOllamaTransport(),
            data_directory=tmp_path / "data",
        )

        assert runtime.service_container.get(Brain) is runtime.brain

        shutdown_runtime(runtime)

    def test_no_ollama_warmup_on_startup(self, tmp_path) -> None:
        """
        Verify that PARIKA startup does not send a warm-up request to Ollama.

        The local model must not be proactively loaded into GPU memory
        during startup. It should only load on-demand when actually used
        as a fallback after all cloud providers fail.
        """
        transport = _FakeOllamaTransport(
            models=[{"name": "qwen3.5:4b"}]
        )

        runtime = build_default_runtime(
            ollama_transport=transport,
            data_directory=tmp_path / "data",
        )

        # Verify no /api/chat call was made during startup (no warm-up)
        assert transport.chat_calls == [], (
            "Expected no chat calls during startup, but got: "
            f"{transport.chat_calls}"
        )

        # Verify Ollama provider is still registered and models discovered
        provider = runtime.provider_manager.get(OLLAMA_PROVIDER_ID)
        assert provider.enabled is True
        assert len(provider.models) == 1
        assert provider.health is not None
        assert provider.health.available is True

        shutdown_runtime(runtime)

    def test_no_keep_alive_in_chat_payload(self, tmp_path) -> None:
        """
        Verify that Ollama chat requests do not include a PARIKA-configured
        keep_alive parameter for persistent model residency.

        The local model must load on-demand when invoked as the final
        fallback, and PARIKA must not request that Ollama keep the model
        resident after inference completes.
        """
        transport = _FakeOllamaTransport(
            models=[{"name": "qwen3.5:4b"}]
        )

        runtime = build_default_runtime(
            ollama_transport=transport,
            data_directory=tmp_path / "data",
        )

        # Simulate a local fallback inference by directly invoking the driver
        provider = runtime.provider_manager.get(OLLAMA_PROVIDER_ID)
        model = provider.models[0]

        from parika.providers.ollama.requests import OllamaChatRequest
        from parika.providers.ollama.messages import OllamaMessage

        request = OllamaChatRequest(
            messages=(OllamaMessage(role="user", content="test"),),
        )

        # Execute the chat - this should not include keep_alive in the payload
        driver = runtime.provider_manager._drivers[OLLAMA_PROVIDER_ID]
        driver.chat(model, request)

        # Verify no keep_alive was sent in any chat payload
        for payload in transport.chat_calls:
            assert "keep_alive" not in payload, (
                f"Expected no keep_alive in chat payload, but found: {payload}"
            )

        shutdown_runtime(runtime)


class TestShutdownRuntime:
    def test_unloads_active_modules(self, tmp_path) -> None:
        runtime = build_default_runtime(
            ollama_transport=_FakeOllamaTransport(),
            data_directory=tmp_path / "data",
        )

        shutdown_runtime(runtime)

        assert runtime.module_manager.get_active() == ()
