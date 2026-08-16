"""
PARIKA Ollama Provider - Wire Payload Helpers

Small, stateless functions that translate between PARIKA domain
objects and Ollama's JSON wire format, and a couple of narrow response
heuristics used by the driver. Kept separate from `driver.py` so the
driver itself stays focused on orchestration (see
`PARIKA_Core_Coding_Standards.md` - File Size Guidelines).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.response import ProviderResponse
from parika.core.tool_manager.response import ToolResponse

from .messages import OllamaMessage, OllamaToolCall
from .requests import OllamaChatRequest, OllamaGenerateRequest


def looks_like_model_not_found(message: str) -> bool:
    """
    Heuristically detect Ollama's "model not found" error text.

    Ollama reports a missing model as an HTTP 404 with a body such as
    `{"error": "model \\"x\\" not found, try pulling it first"}`; this
    checks the rendered error message produced by `OllamaTransport`
    rather than depending on a specific status code helper.
    """

    return "not found" in message.lower()


def build_options_payload(options: RequestOptions) -> dict[str, Any]:
    """
    Translate a provider-independent `RequestOptions` into Ollama's
    `options` payload fields.

    `options.context_window_tokens` -- the Runtime Context Budget's
    `effective_context_window`, computed dynamically by Planner from
    the selected model's own capabilities (see `provider_manager
    .context_budget`) -- becomes Ollama's `num_ctx` field. This is
    the Ollama-specific translation the Runtime Context Budget
    architecture reserves entirely for the Provider: Core and AI
    Context Engineering never reference `num_ctx` themselves.
    """

    payload: dict[str, Any] = {}

    if options.temperature is not None:
        payload["temperature"] = options.temperature

    if options.top_p is not None:
        payload["top_p"] = options.top_p

    if options.max_output_tokens is not None:
        payload["num_predict"] = options.max_output_tokens

    if options.context_window_tokens is not None:
        payload["num_ctx"] = options.context_window_tokens

    if options.stop_sequences:
        payload["stop"] = list(options.stop_sequences)

    if options.seed is not None:
        payload["seed"] = options.seed

    return payload


def build_generate_request_payload(
    model_id: str,
    request: OllamaGenerateRequest,
) -> dict[str, Any]:
    """
    Build the JSON payload for a `POST /api/generate` call.

    Translates the generic, provider-independent
    `RequestOptions.reasoning` preference into Ollama's own `think`
    request field when Planner has expressed an explicit preference
    (see `RequestOptions.reasoning`'s docstring). Ollama-specific
    translation happens only here, inside the provider implementation
    - Planner and Core never reference `think` or any other
    Ollama-specific field name.
    """

    payload: dict[str, Any] = {
        "model": model_id,
        "prompt": request.prompt,
        "stream": request.on_token is not None,
    }

    if request.system is not None:
        payload["system"] = request.system

    if request.options.reasoning is not None:
        payload["think"] = request.options.reasoning

    options_payload = build_options_payload(request.options)

    if options_payload:
        payload["options"] = options_payload

    return payload


def build_chat_request_payload(
    model_id: str,
    messages: Sequence[OllamaMessage],
    request: OllamaChatRequest,
) -> dict[str, Any]:
    """
    Build the JSON payload for a `POST /api/chat` call.

    See `build_generate_request_payload()` for the `think` field
    translation, which applies identically here.
    """

    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [message.to_payload() for message in messages],
        "stream": request.on_token is not None,
    }

    if request.tools:
        payload["tools"] = [tool.to_payload() for tool in request.tools]

    if request.options.reasoning is not None:
        payload["think"] = request.options.reasoning

    options_payload = build_options_payload(request.options)

    if options_payload:
        payload["options"] = options_payload

    return payload


def parse_tool_calls(raw: Any) -> tuple[OllamaToolCall, ...]:
    """
    Parse the `tool_calls` field of an Ollama chat message payload.

    Most models report `function.arguments` as a JSON object directly,
    but some model templates instead emit it as a JSON-encoded string
    (e.g. `"arguments": "{\\"query\\": \\"x\\"}"`); both shapes are
    accepted so tool calling stays reliable across model templates
    without depending on any specific one.
    """

    if not isinstance(raw, list):
        return ()

    calls: list[OllamaToolCall] = []

    for entry in raw:
        if not isinstance(entry, dict):
            continue

        function = entry.get("function")

        if not isinstance(function, dict):
            continue

        name = function.get("name")

        if not isinstance(name, str) or not name:
            continue

        arguments = _coerce_tool_call_arguments(function.get("arguments"))

        call_id = entry.get("id")
        call_id = call_id if isinstance(call_id, str) else None

        calls.append(
            OllamaToolCall(
                name=name,
                arguments=arguments,
                id=call_id,
            )
        )

    return tuple(calls)


def _coerce_tool_call_arguments(raw: Any) -> dict[str, Any]:
    """
    Normalize a tool call's `arguments` value into a plain dict,
    accepting either a JSON object (the common case) or a
    JSON-encoded string of one (an observed alternative some model
    templates emit).
    """

    if isinstance(raw, dict):
        return raw

    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}

        return parsed if isinstance(parsed, dict) else {}

    return {}


def serialize_task_result(task_response: Any) -> dict[str, Any]:
    """
    Serialize a Task's response into a plain JSON-compatible payload
    describing the outcome of an executed capability, for feeding
    back to a model as a "tool" role message.
    """

    if task_response is None:
        return {"result": None}

    backend_response = task_response.outputs.get("result")

    if isinstance(backend_response, ToolResponse):
        return {
            "result": backend_response.result,
            "attributes": dict(backend_response.attributes),
        }

    if isinstance(backend_response, ProviderResponse):
        return {
            "result": getattr(backend_response, "text", str(backend_response))
        }

    return {"result": backend_response}
