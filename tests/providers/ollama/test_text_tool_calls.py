"""
Unit tests for `parika.providers.ollama.text_tool_calls`.

Covers the exact malformed output reproduced against a real Ollama
server (`qwen3-coder:latest`, multiple tools advertised - see the
module docstring), plus the Hermes/ChatML-style alternative, and
confirms ordinary prose is never misinterpreted as a tool call.
"""

from __future__ import annotations

from parika.providers.ollama.text_tool_calls import (
    looks_like_text_tool_call,
    parse_text_tool_calls,
)


class TestLooksLikeTextToolCall:
    def test_true_for_xml_style_markup(self) -> None:
        assert looks_like_text_tool_call("<function=get_current_datetime>")

    def test_true_for_hermes_style_markup(self) -> None:
        assert looks_like_text_tool_call('<tool_call>{"name": "x"}')

    def test_false_for_ordinary_prose(self) -> None:
        assert not looks_like_text_tool_call("The current time is 3pm.")

    def test_false_for_empty_string(self) -> None:
        assert not looks_like_text_tool_call("")


class TestParseTextToolCallsXmlStyle:
    def test_parses_reproduced_qwen3_coder_output(self) -> None:
        """
        The exact content observed from a real Ollama server
        (`qwen3-coder:latest`) when two tools were advertised for a
        "What is the current time in IST?" request.
        """

        content = (
            "<function=get_current_datetime>\n"
            "<parameter=timezone>\n"
            "IST\n"
            "</parameter>\n"
            "</function>\n"
            "</tool_call>"
        )

        calls = parse_text_tool_calls(content)

        assert len(calls) == 1
        assert calls[0].name == "get_current_datetime"
        assert calls[0].arguments == {"timezone": "IST"}

    def test_parses_multiple_parameters(self) -> None:
        content = (
            "<function=web_search>\n"
            "<parameter=query>\nlatest AI news\n</parameter>\n"
            "<parameter=max_results>\n5\n</parameter>\n"
            "</function>"
        )

        calls = parse_text_tool_calls(content)

        assert len(calls) == 1
        assert calls[0].name == "web_search"
        assert calls[0].arguments == {
            "query": "latest AI news",
            "max_results": 5,
        }

    def test_parses_multiple_function_blocks(self) -> None:
        content = (
            "<function=get_current_datetime>\n"
            "<parameter=timezone>UTC</parameter>\n"
            "</function>\n"
            "<function=web_search>\n"
            "<parameter=query>weather</parameter>\n"
            "</function>"
        )

        calls = parse_text_tool_calls(content)

        assert [call.name for call in calls] == [
            "get_current_datetime",
            "web_search",
        ]

    def test_handles_function_with_no_parameters(self) -> None:
        content = "<function=noop></function>"

        calls = parse_text_tool_calls(content)

        assert len(calls) == 1
        assert calls[0].name == "noop"
        assert dict(calls[0].arguments) == {}

    def test_tolerates_missing_closing_function_tag(self) -> None:
        content = "<function=get_current_datetime>\n<parameter=timezone>UTC</parameter>"

        calls = parse_text_tool_calls(content)

        assert len(calls) == 1
        assert calls[0].name == "get_current_datetime"


class TestParseTextToolCallsHermesStyle:
    def test_parses_hermes_json_block(self) -> None:
        content = (
            '<tool_call>\n{"name": "get_current_datetime", '
            '"arguments": {"timezone": "IST"}}\n</tool_call>'
        )

        calls = parse_text_tool_calls(content)

        assert len(calls) == 1
        assert calls[0].name == "get_current_datetime"
        assert calls[0].arguments == {"timezone": "IST"}

    def test_parses_multiple_hermes_blocks(self) -> None:
        content = (
            '<tool_call>{"name": "a", "arguments": {}}</tool_call>'
            '<tool_call>{"name": "b", "arguments": {"x": 1}}</tool_call>'
        )

        calls = parse_text_tool_calls(content)

        assert [call.name for call in calls] == ["a", "b"]
        assert calls[1].arguments == {"x": 1}

    def test_ignores_invalid_json_inside_tool_call_tag(self) -> None:
        content = "<tool_call>not valid json</tool_call>"

        calls = parse_text_tool_calls(content)

        assert calls == ()

    def test_ignores_block_missing_name(self) -> None:
        content = '<tool_call>{"arguments": {}}</tool_call>'

        calls = parse_text_tool_calls(content)

        assert calls == ()

    def test_hermes_style_takes_precedence_over_xml_style(self) -> None:
        content = (
            '<tool_call>{"name": "hermes_call", "arguments": {}}</tool_call>'
        )

        calls = parse_text_tool_calls(content)

        assert len(calls) == 1
        assert calls[0].name == "hermes_call"


class TestParseTextToolCallsDoesNotMisfire:
    def test_ordinary_prose_yields_no_calls(self) -> None:
        assert parse_text_tool_calls("The current time is 3pm in UTC.") == ()

    def test_empty_content_yields_no_calls(self) -> None:
        assert parse_text_tool_calls("") == ()

    def test_prose_mentioning_function_word_yields_no_calls(self) -> None:
        assert parse_text_tool_calls(
            "This function computes the average."
        ) == ()
