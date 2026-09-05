import json
from types import SimpleNamespace

import pytest

from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.options import RequestOptions
from parika.providers.openai_compatible.driver import OpenAICompatibleProviderDriver


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request_json(self, method, url, *, payload, headers, timeout):
        self.calls.append((method, url, payload, headers))
        return self.response

    def stream_lines(self, method, url, *, payload, headers, timeout):
        self.calls.append((method, url, payload, headers))
        yield {"choices": [{"delta": {"content": "hello"}}]}
        yield {"choices": [{"delta": {"content": " world"}}], "usage": {"total_tokens": 3}}


def driver(monkeypatch, transport):
    monkeypatch.setenv("PARIKA_TEST_PROVIDER_KEY", "secret-value")
    return OpenAICompatibleProviderDriver(
        provider_id="arbitrary", base_url="https://example.invalid/v1",
        model="model-x", api_key_env="PARIKA_TEST_PROVIDER_KEY",
        logger=SimpleNamespace(get_logger=lambda _: SimpleNamespace()),
        transport=transport,
    )


def test_normalizes_completion_and_usage(monkeypatch):
    d = driver(monkeypatch, FakeTransport({"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}))
    result = d.execute(d.discover_models()[0], ChatRequest(messages=(ChatMessage(role="user", content="hi"),)))
    assert result.message.content == "ok"
    assert result.metadata["usage"]["total_tokens"] == 3


def test_streams_only_text(monkeypatch):
    seen = []
    d = driver(monkeypatch, FakeTransport({}))
    model = d.discover_models()[0]
    result = d.execute(model, ChatRequest(messages=(ChatMessage(role="user", content="hi"),), options=RequestOptions(stream=True), on_token=seen.append))
    assert result.message.content == "hello world"
    assert seen == ["hello", " world"]


def test_missing_key_is_configuration_error(monkeypatch):
    monkeypatch.delenv("PARIKA_MISSING", raising=False)
    with pytest.raises(Exception, match="not set"):
        OpenAICompatibleProviderDriver(provider_id="x", base_url="https://x/v1", model="m", api_key_env="PARIKA_MISSING", logger=SimpleNamespace(get_logger=lambda _: SimpleNamespace()))
