"""
Unit tests for the provider-independent chat types: `ChatMessage`,
`ToolSpec`, `ChatRequest`, `ChatResult`, and `ToolInvocation`.

These are the generic boundary every provider-independent layer
(Interfaces, AI Context Engineering, Modules) builds and reads;
concrete providers (e.g. Ollama, via `providers.ollama.chat_adapter`)
convert to/from their own wire-specific types at the provider
boundary. See `tests/providers/ollama/test_chat_adapter.py` for the
Ollama-side conversion coverage.
"""

from __future__ import annotations

from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult, ToolInvocation
from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse
from parika.core.provider_manager.tool_spec import ToolSpec


class TestChatMessage:
    def test_defaults(self) -> None:
        message = ChatMessage(role="user")

        assert message.role == "user"
        assert message.content == ""
        assert message.images == ()

    def test_images_are_coerced_to_a_tuple(self) -> None:
        message = ChatMessage(role="user", content="describe", images=["a", "b"])

        assert message.images == ("a", "b")


class TestToolSpec:
    def test_defaults(self) -> None:
        tool = ToolSpec(name="get_current_datetime", description="Returns now.")

        assert tool.name == "get_current_datetime"
        assert tool.capability_id == ""
        assert dict(tool.parameters) == {}

    def test_parameters_are_immutable(self) -> None:
        tool = ToolSpec(
            name="t", description="d", parameters={"type": "object"}
        )

        assert dict(tool.parameters) == {"type": "object"}


class TestChatRequest:
    def test_is_a_provider_request(self) -> None:
        request = ChatRequest(messages=(ChatMessage(role="user", content="hi"),))

        assert isinstance(request, ProviderRequest)
        assert request.tools == ()
        assert request.on_token is None
        assert isinstance(request.options, RequestOptions)

    def test_messages_and_tools_are_coerced_to_tuples(self) -> None:
        request = ChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            tools=[ToolSpec(name="t", description="d")],
        )

        assert isinstance(request.messages, tuple)
        assert isinstance(request.tools, tuple)

    def test_carries_generic_options(self) -> None:
        request = ChatRequest(
            messages=(ChatMessage(role="user", content="hi"),),
            options=RequestOptions(estimated_prompt_tokens=10),
        )

        assert request.options.estimated_prompt_tokens == 10


class TestChatResult:
    def test_is_a_provider_response(self) -> None:
        result = ChatResult(message=ChatMessage(role="assistant", content="hi"))

        assert isinstance(result, ProviderResponse)
        assert result.tool_invocations == ()

    def test_tool_invocations_are_coerced_to_a_tuple(self) -> None:
        invocation = ToolInvocation(
            name="web_search", capability_id="web.search", succeeded=True, content="{}"
        )
        result = ChatResult(
            message=ChatMessage(role="assistant", content="hi"),
            tool_invocations=[invocation],
        )

        assert isinstance(result.tool_invocations, tuple)
        assert result.tool_invocations[0] is invocation
