"""
PARIKA Core - ProviderManager Component

Defines the provider-independent conversational result type.

`ChatResult` is the generic analogue of a concrete provider's own chat
response type (e.g. Ollama's `OllamaChatResponse`): the normalized
outcome of one conversational turn that every provider-independent
layer (Interfaces, Modules) consumes, with no provider-specific wire
concept. The Provider selected by Planner produces this from its own
concrete response at the provider boundary (`ProviderDriver.execute()`
for a `ChatRequest`), exactly like every other `ProviderResponse`
subtype.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chat_message import ChatMessage
from .response import ProviderResponse


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolInvocation:
    """
    Immutable record of one tool call executed through Brain during a
    chat turn.

    Attributes:
        name:
            Tool name the model used to request this call.

        capability_id:
            PARIKA capability id the call was mapped to, or None if
            the model requested a tool name that was not advertised.

        succeeded:
            Whether the underlying Goal completed successfully.

        content:
            Textual content fed back to the model as this call's
            result.
    """

    name: str
    capability_id: str | None
    succeeded: bool
    content: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatResult(ProviderResponse):
    """
    Provider-independent outcome of one conversational turn.

    Attributes:
        message:
            The model's final answer. Never carries tool-calling wire
            structure: the Provider resolves every tool call
            internally before returning, so callers always receive a
            directly displayable answer.

        tool_invocations:
            Every tool call executed through Brain while producing
            this result, in the order they were invoked. Empty when
            the model answered directly without calling any tool.
    """

    message: ChatMessage
    tool_invocations: tuple[ToolInvocation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tool_invocations",
            tuple(self.tool_invocations),
        )
