"""
Unit tests for Ollama message and tool specification payload
serialization.
"""

from __future__ import annotations

from parika.providers.ollama.messages import (
    OllamaMessage,
    OllamaToolCall,
    OllamaToolSpec,
)


class TestOllamaMessage:
    def test_to_payload_basic_message(self) -> None:
        message = OllamaMessage(role="user", content="hello")

        assert message.to_payload() == {"role": "user", "content": "hello"}

    def test_to_payload_includes_tool_calls(self) -> None:
        call = OllamaToolCall(name="web_search", arguments={"query": "x"})
        message = OllamaMessage(
            role="assistant", content="", tool_calls=(call,)
        )

        payload = message.to_payload()

        assert payload["tool_calls"] == [
            {"function": {"name": "web_search", "arguments": {"query": "x"}}}
        ]

    def test_to_payload_tool_role_includes_name(self) -> None:
        message = OllamaMessage(
            role="tool", content="{}", tool_call_id="1", name="web_search"
        )

        payload = message.to_payload()

        assert payload["name"] == "web_search"

    def test_tool_calls_normalized_to_tuple(self) -> None:
        call = OllamaToolCall(name="x", arguments={})
        message = OllamaMessage(role="assistant", tool_calls=[call])  # type: ignore[arg-type]

        assert isinstance(message.tool_calls, tuple)

    def test_to_payload_omits_images_when_absent(self) -> None:
        message = OllamaMessage(role="user", content="hello")

        assert "images" not in message.to_payload()

    def test_to_payload_includes_images_when_present(self) -> None:
        message = OllamaMessage(
            role="user", content="Extract the text.", images=("YmFzZTY0",)
        )

        payload = message.to_payload()

        assert payload["images"] == ["YmFzZTY0"]

    def test_images_normalized_to_tuple(self) -> None:
        message = OllamaMessage(role="user", images=["YmFzZTY0"])  # type: ignore[arg-type]

        assert isinstance(message.images, tuple)


class TestOllamaToolCall:
    def test_arguments_are_immutable(self) -> None:
        call = OllamaToolCall(name="web_search", arguments={"query": "x"})

        assert call.arguments["query"] == "x"

        try:
            call.arguments["query"] = "y"  # type: ignore[index]
        except TypeError:
            pass
        else:
            raise AssertionError("arguments should be immutable")


class TestOllamaToolSpec:
    def test_to_payload_shape(self) -> None:
        spec = OllamaToolSpec(
            name="web_search",
            description="Search the web.",
            capability_id="web.search",
            parameters={"type": "object", "properties": {}},
        )

        payload = spec.to_payload()

        assert payload == {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
