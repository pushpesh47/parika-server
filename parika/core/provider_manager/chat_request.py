"""
PARIKA Core - ProviderManager Component

Defines the provider-independent conversational request type.

`ChatRequest` is the generic analogue of a concrete provider's own
chat request type (e.g. Ollama's `OllamaChatRequest`): it carries only
what every chat-capable provider needs -- a conversation, an optional
tool roster, and an optional streaming callback -- with no
provider-specific wire concept. Interfaces and Modules build this
type via a Goal's `provider_request_builder`; the Provider selected by
Planner converts it into its own concrete request at the provider
boundary (`ProviderDriver.execute()`), exactly like every other
`ProviderRequest` subtype.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .chat_message import ChatMessage
from .request import ProviderRequest
from .tool_spec import ToolSpec


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatRequest(ProviderRequest):
    """
    Provider-independent request for one conversational turn.

    Attributes:
        messages:
            Conversation history, oldest first, ending with the
            newest user message to respond to.

        tools:
            Capabilities advertised to the model as callable
            tools/functions.

        on_token:
            Optional callback invoked with each incrementally
            streamed content fragment of the model's final answer.
            Providers with no streaming support simply ignore it.
    """

    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolSpec, ...] = ()
    on_token: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
