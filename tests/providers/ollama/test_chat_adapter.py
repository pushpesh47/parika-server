"""
Unit tests for `parika.providers.ollama.chat_adapter` -- the one,
isolated place a provider-independent `ChatRequest`/`ChatResult` is
ever converted to/from this provider's own `OllamaChatRequest`/
`OllamaChatResponse`.
"""

from __future__ import annotations

from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.tool_spec import ToolSpec
from parika.providers.ollama.chat_adapter import (
    to_chat_result,
    to_ollama_chat_request,
)
from parika.providers.ollama.messages import OllamaMessage, OllamaToolCall
from parika.providers.ollama.requests import OllamaChatRequest
from parika.providers.ollama.responses import OllamaChatResponse, OllamaToolInvocation


class TestToOllamaChatRequest:
    def test_converts_messages_preserving_order_and_content(self) -> None:
        request = ChatRequest(
            messages=(
                ChatMessage(role="system", content="be helpful"),
                ChatMessage(role="user", content="hi"),
            )
        )

        ollama_request = to_ollama_chat_request(request)

        assert isinstance(ollama_request, OllamaChatRequest)
        assert [m.role for m in ollama_request.messages] == ["system", "user"]
        assert [m.content for m in ollama_request.messages] == ["be helpful", "hi"]

    def test_converts_multimodal_images(self) -> None:
        request = ChatRequest(
            messages=(
                ChatMessage(role="user", content="describe this", images=("b64",)),
            )
        )

        ollama_request = to_ollama_chat_request(request)

        assert ollama_request.messages[0].images == ("b64",)

    def test_converts_tool_specs(self) -> None:
        request = ChatRequest(
            messages=(ChatMessage(role="user", content="hi"),),
            tools=(
                ToolSpec(
                    name="get_current_datetime",
                    description="Returns the current date and time.",
                    parameters={"type": "object", "properties": {}},
                    capability_id="runtime.current_datetime",
                ),
            ),
        )

        ollama_request = to_ollama_chat_request(request)

        assert len(ollama_request.tools) == 1
        tool = ollama_request.tools[0]
        assert tool.name == "get_current_datetime"
        assert tool.capability_id == "runtime.current_datetime"
        assert tool.to_payload() == {
            "type": "function",
            "function": {
                "name": "get_current_datetime",
                "description": "Returns the current date and time.",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def test_preserves_on_token_and_options(self) -> None:
        fragments: list[str] = []
        request = ChatRequest(
            messages=(ChatMessage(role="user", content="hi"),),
            on_token=fragments.append,
            options=RequestOptions(estimated_prompt_tokens=42),
        )

        ollama_request = to_ollama_chat_request(request)

        ollama_request.on_token("chunk")
        assert fragments == ["chunk"]
        assert ollama_request.options.estimated_prompt_tokens == 42


class TestToChatResult:
    def test_converts_final_message(self) -> None:
        response = OllamaChatResponse(
            model_id="qwen3:8b",
            message=OllamaMessage(role="assistant", content="Hello!"),
        )

        result = to_chat_result(response)

        assert result.model_id == "qwen3:8b"
        assert result.message.role == "assistant"
        assert result.message.content == "Hello!"
        assert result.tool_invocations == ()

    def test_converts_tool_invocations(self) -> None:
        response = OllamaChatResponse(
            message=OllamaMessage(role="assistant", content="Done."),
            tool_invocations=(
                OllamaToolInvocation(
                    tool_call=OllamaToolCall(name="web_search", arguments={}),
                    capability_id="web.search",
                    succeeded=True,
                    content="{}",
                ),
            ),
        )

        result = to_chat_result(response)

        assert len(result.tool_invocations) == 1
        invocation = result.tool_invocations[0]
        assert invocation.name == "web_search"
        assert invocation.capability_id == "web.search"
        assert invocation.succeeded is True
        assert invocation.content == "{}"
