"""
PARIKA Ollama Provider - Text-Based Tool Call Fallback Parsing

Some locally-hosted models occasionally fail to populate Ollama's
native `message.tool_calls` JSON field even though they clearly intend
to call a tool, instead leaking their chat template's raw tool-call
markup into `message.content` as plain text. This is a known quirk of
certain Ollama model templates - for example, `qwen3-coder:latest` was
observed (via direct API reproduction) emitting

    <function=get_current_datetime>
    <parameter=timezone>
    IST
    </parameter>
    </function>
    </tool_call>

as `message.content`, with `message.tool_calls` empty, specifically
when multiple tools were advertised - even though the exact same
request format worked correctly (populating `tool_calls` natively) for
every other locally tested model, and for the same model with a single
tool advertised. This confirms the wire format PARIKA sends is
correct; the model's own template occasionally fails to fully render
into Ollama's native field.

This module recovers such tool calls generically, by recognizing
common template *markup shapes* - a Hermes/ChatML-style
`<tool_call>{...}</tool_call>` JSON block, and an XML-style
`<function=NAME><parameter=KEY>VALUE</parameter></function>` block -
never by recognizing any specific tool or capability name. It works
identically for any current or future Tool-backed capability, and
never runs at all unless the model was actually offered at least one
tool for this turn.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .messages import OllamaToolCall

_HERMES_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*(?:</tool_call>|$)", re.DOTALL
)
_XML_FUNCTION_RE = re.compile(
    r"<function=([\w.\-]+)>(.*?)(?:</function>|$)", re.DOTALL
)
_XML_PARAMETER_RE = re.compile(
    r"<parameter=([\w.\-]+)>\s*(.*?)\s*</parameter>", re.DOTALL
)

MARKUP_HINTS = ("<tool_call>", "<function=")
"""
Cheap pre-check substrings. Fallback parsing only runs when at least
one is present, so ordinary prose is never misinterpreted as a tool
call and no regex work happens on the (overwhelmingly common) case of
a normal, well-formed answer.

Public (not `_`-prefixed) so `stream_filter.ToolMarkupStreamFilter`
can recognize the exact same markup shapes while filtering the live
stream, keeping streaming suppression and post-hoc recovery in
agreement about what counts as leaked markup.
"""


def looks_like_text_tool_call(content: str) -> bool:
    """
    Cheaply check whether `content` might contain leaked tool-call
    template markup, before attempting the more expensive regex-based
    parse.
    """

    return any(hint in content for hint in MARKUP_HINTS)


def parse_text_tool_calls(content: str) -> tuple[OllamaToolCall, ...]:
    """
    Attempt to recover tool calls from leaked template markup in
    `content`.

    Args:
        content:
            An assistant message's `content` field, with an empty
            native `tool_calls` field.

    Returns:
        Every tool call recovered, in the order they appear in
        `content`. Empty when nothing matches either recognized
        markup shape.
    """

    if not content or not looks_like_text_tool_call(content):
        return ()

    hermes_calls = _parse_hermes_style(content)

    if hermes_calls:
        return hermes_calls

    return _parse_xml_style(content)


def _parse_hermes_style(content: str) -> tuple[OllamaToolCall, ...]:
    """
    Parse `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`
    blocks (the Hermes/ChatML tool-calling convention some model
    templates use).
    """

    calls: list[OllamaToolCall] = []

    for match in _HERMES_TOOL_CALL_RE.finditer(content):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        if not isinstance(payload, dict):
            continue

        name = payload.get("name")

        if not isinstance(name, str) or not name:
            continue

        arguments = payload.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}

        calls.append(OllamaToolCall(name=name, arguments=arguments))

    return tuple(calls)


def _parse_xml_style(content: str) -> tuple[OllamaToolCall, ...]:
    """
    Parse `<function=NAME><parameter=KEY>VALUE</parameter></function>`
    blocks (an XML-flavored tool-calling convention some model
    templates use).
    """

    calls: list[OllamaToolCall] = []

    for match in _XML_FUNCTION_RE.finditer(content):
        name = match.group(1)
        body = match.group(2)

        arguments = {
            key: _coerce_parameter_value(value.strip())
            for key, value in _XML_PARAMETER_RE.findall(body)
        }

        calls.append(OllamaToolCall(name=name, arguments=arguments))

    return tuple(calls)


def _coerce_parameter_value(value: str) -> Any:
    """
    Best-effort coercion of an XML-style parameter's text value into a
    JSON-compatible type (number/bool/null/object/array), falling back
    to the raw string when it is not valid JSON (the common case for
    plain string arguments).
    """

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
