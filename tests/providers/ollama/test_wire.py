"""
Unit tests for `parika.providers.ollama.wire`.
"""

from __future__ import annotations

from parika.providers.ollama.messages import OllamaMessage, OllamaToolSpec
from parika.providers.ollama.requests import OllamaChatRequest, OllamaGenerateRequest
from parika.providers.ollama.wire import (
    build_chat_request_payload,
    build_generate_request_payload,
    build_options_payload,
    looks_like_model_not_found,
    parse_tool_calls,
)


class TestParseToolCallsNativeField:
    def test_returns_empty_tuple_for_non_list(self) -> None:
        assert parse_tool_calls(None) == ()
        assert parse_tool_calls("not a list") == ()
        assert parse_tool_calls({}) == ()

    def test_parses_dict_arguments(self) -> None:
        calls = parse_tool_calls(
            [{"function": {"name": "web_search", "arguments": {"query": "x"}}}]
        )

        assert len(calls) == 1
        assert calls[0].name == "web_search"
        assert calls[0].arguments == {"query": "x"}

    def test_parses_json_encoded_string_arguments(self) -> None:
        """
        Some model templates emit `arguments` as a JSON-encoded string
        rather than a JSON object; both shapes must be accepted.
        """

        calls = parse_tool_calls(
            [
                {
                    "function": {
                        "name": "web_search",
                        "arguments": '{"query": "x", "max_results": 5}',
                    }
                }
            ]
        )

        assert len(calls) == 1
        assert calls[0].arguments == {"query": "x", "max_results": 5}

    def test_invalid_json_string_arguments_yields_empty_dict(self) -> None:
        calls = parse_tool_calls(
            [{"function": {"name": "x", "arguments": "not json"}}]
        )

        assert calls[0].arguments == {}

    def test_json_array_string_arguments_yields_empty_dict(self) -> None:
        calls = parse_tool_calls(
            [{"function": {"name": "x", "arguments": "[1, 2, 3]"}}]
        )

        assert calls[0].arguments == {}

    def test_missing_arguments_yields_empty_dict(self) -> None:
        calls = parse_tool_calls([{"function": {"name": "x"}}])

        assert calls[0].arguments == {}

    def test_skips_entries_missing_a_name(self) -> None:
        calls = parse_tool_calls([{"function": {"arguments": {}}}])

        assert calls == ()

    def test_skips_non_dict_entries(self) -> None:
        calls = parse_tool_calls(["not a dict"])

        assert calls == ()

    def test_parses_call_id_when_present(self) -> None:
        calls = parse_tool_calls(
            [{"id": "call_123", "function": {"name": "x", "arguments": {}}}]
        )

        assert calls[0].id == "call_123"

    def test_parses_multiple_calls(self) -> None:
        calls = parse_tool_calls(
            [
                {"function": {"name": "a", "arguments": {}}},
                {"function": {"name": "b", "arguments": {"x": 1}}},
            ]
        )

        assert [call.name for call in calls] == ["a", "b"]


class TestLooksLikeModelNotFound:
    def test_true_for_not_found_message(self) -> None:
        assert looks_like_model_not_found("model \"x\" not found")

    def test_case_insensitive(self) -> None:
        assert looks_like_model_not_found("Model X Not Found")

    def test_false_for_unrelated_message(self) -> None:
        assert not looks_like_model_not_found("connection refused")


class TestBuildOptionsPayload:
    def test_empty_options_yields_empty_payload(self) -> None:
        from parika.core.provider_manager.options import RequestOptions

        assert build_options_payload(RequestOptions()) == {}

    def test_includes_every_set_option(self) -> None:
        from parika.core.provider_manager.options import RequestOptions

        options = RequestOptions(
            temperature=0.5,
            top_p=0.9,
            max_output_tokens=100,
            stop_sequences=("STOP",),
            seed=42,
            context_window_tokens=32768,
        )

        payload = build_options_payload(options)

        assert payload == {
            "temperature": 0.5,
            "top_p": 0.9,
            "num_predict": 100,
            "num_ctx": 32768,
            "stop": ["STOP"],
            "seed": 42,
        }

    def test_context_window_tokens_translates_to_num_ctx(self) -> None:
        from parika.core.provider_manager.options import RequestOptions

        payload = build_options_payload(
            RequestOptions(context_window_tokens=40960)
        )

        assert payload == {"num_ctx": 40960}

    def test_omits_num_ctx_when_context_window_tokens_unset(self) -> None:
        from parika.core.provider_manager.options import RequestOptions

        payload = build_options_payload(RequestOptions())

        assert "num_ctx" not in payload


class TestBuildChatRequestPayload:
    def test_includes_tools_when_present(self) -> None:
        payload = build_chat_request_payload(
            "model-a",
            [OllamaMessage(role="user", content="hi")],
            OllamaChatRequest(
                messages=(),
                tools=(
                    OllamaToolSpec(
                        name="web_search",
                        description="Search.",
                        capability_id="web.search",
                    ),
                ),
            ),
        )

        assert payload["tools"][0]["function"]["name"] == "web_search"

    def test_omits_tools_key_when_no_tools(self) -> None:
        payload = build_chat_request_payload(
            "model-a",
            [OllamaMessage(role="user", content="hi")],
            OllamaChatRequest(messages=()),
        )

        assert "tools" not in payload

    def test_stream_reflects_on_token_presence(self) -> None:
        payload = build_chat_request_payload(
            "model-a",
            [OllamaMessage(role="user", content="hi")],
            OllamaChatRequest(messages=(), on_token=lambda fragment: None),
        )

        assert payload["stream"] is True

    def test_includes_think_field_when_reasoning_set(self) -> None:
        from dataclasses import replace

        request = OllamaChatRequest(messages=())
        request = replace(
            request, options=replace(request.options, reasoning=True)
        )

        payload = build_chat_request_payload("model-a", [], request)

        assert payload["think"] is True


class TestBuildGenerateRequestPayload:
    def test_includes_system_when_present(self) -> None:
        payload = build_generate_request_payload(
            "model-a", OllamaGenerateRequest(prompt="hi", system="Be nice.")
        )

        assert payload["system"] == "Be nice."

    def test_omits_system_when_absent(self) -> None:
        payload = build_generate_request_payload(
            "model-a", OllamaGenerateRequest(prompt="hi")
        )

        assert "system" not in payload
