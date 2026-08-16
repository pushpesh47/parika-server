"""
PARIKA Ollama Provider - Responses

Defines the concrete `ProviderResponse` subtypes returned by the
Ollama provider driver.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from parika.core.provider_manager.response import ProviderResponse

from .messages import OllamaMessage, OllamaToolCall


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaToolInvocation:
    """
    Immutable record of a single tool call executed through Brain
    during a chat loop.
    """

    tool_call: OllamaToolCall
    """
    Tool call as requested by the model.
    """

    capability_id: str | None
    """
    PARIKA capability id the call was mapped to, or None if the model
    requested a tool name that was not advertised.
    """

    succeeded: bool
    """
    Whether the underlying Goal completed successfully.
    """

    content: str
    """
    Textual content fed back to the model as the "tool" role message
    answering this call.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaChatResponse(ProviderResponse):
    """
    Response produced by the Ollama `/api/chat` endpoint.
    """

    message: OllamaMessage
    """
    Final assistant message. Never carries `tool_calls`: the driver
    resolves every tool call internally before returning, so callers
    always receive a directly displayable answer.
    """

    done: bool = True
    """
    Whether Ollama reported the response as complete.
    """

    tool_invocations: tuple[OllamaToolInvocation, ...] = ()
    """
    Every tool call executed through Brain while producing this
    response, in the order they were invoked. Empty when the model
    answered directly without calling any tool.
    """

    total_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tool_invocations",
            tuple(self.tool_invocations),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaGenerateResponse(ProviderResponse):
    """
    Response produced by the Ollama `/api/generate` endpoint.
    """

    text: str
    """
    Generated completion text.
    """

    done: bool = True

    total_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None
