"""
PARIKA Ollama Provider - Chat Request/Result Adapter

Translates between PARIKA's provider-independent chat types
(`parika.core.provider_manager.chat_request.ChatRequest` /
`chat_result.ChatResult`) and this provider's own concrete wire types
(`OllamaChatRequest` / `OllamaChatResponse`), at the provider boundary
(`OllamaProviderDriver.execute()`).

Every provider-independent layer (Interfaces, AI Context Engineering,
Modules) builds and consumes only the generic types; this module is
the one, isolated place Ollama's own `OllamaMessage`/`OllamaToolSpec`/
`OllamaToolInvocation` shapes are ever produced from, or reduced to,
the generic representation. A future provider (OpenAI, Gemini,
Claude) would own an equivalent, self-contained adapter of its own --
nothing here is shared or reused across providers.
"""

from __future__ import annotations

from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult, ToolInvocation
from parika.core.provider_manager.tool_spec import ToolSpec

from .messages import OllamaMessage, OllamaToolSpec
from .requests import OllamaChatRequest
from .responses import OllamaChatResponse, OllamaToolInvocation


def to_ollama_chat_request(request: ChatRequest) -> OllamaChatRequest:
    """
    Convert a provider-independent `ChatRequest` into this provider's
    own `OllamaChatRequest`, preserving message order, tool roster,
    the streaming callback, and every generic `RequestOptions` value.
    """

    return OllamaChatRequest(
        messages=tuple(
            _to_ollama_message(message) for message in request.messages
        ),
        tools=tuple(_to_ollama_tool_spec(tool) for tool in request.tools),
        on_token=request.on_token,
        options=request.options,
    )


def to_chat_result(response: OllamaChatResponse) -> ChatResult:
    """
    Convert this provider's own `OllamaChatResponse` into a
    provider-independent `ChatResult`.
    """

    return ChatResult(
        model_id=response.model_id,
        metadata=response.metadata,
        message=_to_chat_message(response.message),
        tool_invocations=tuple(
            _to_tool_invocation(invocation)
            for invocation in response.tool_invocations
        ),
    )


def _to_ollama_message(message: ChatMessage) -> OllamaMessage:
    return OllamaMessage(
        role=message.role,
        content=message.content,
        images=message.images,
    )


def _to_chat_message(message: OllamaMessage) -> ChatMessage:
    return ChatMessage(
        role=message.role,
        content=message.content,
        images=message.images,
    )


def _to_ollama_tool_spec(tool: ToolSpec) -> OllamaToolSpec:
    return OllamaToolSpec(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
        capability_id=tool.capability_id,
    )


def _to_tool_invocation(invocation: OllamaToolInvocation) -> ToolInvocation:
    return ToolInvocation(
        name=invocation.tool_call.name,
        capability_id=invocation.capability_id,
        succeeded=invocation.succeeded,
        content=invocation.content,
    )
