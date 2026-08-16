"""
PARIKA Ollama Provider - Requests

Defines the concrete `ProviderRequest` subtypes accepted by the Ollama
provider driver.

`ProviderRequest` (`parika.core.provider_manager.request`) is an
intentionally minimal abstract base shared by every provider; concrete
request payloads are provider-specific by design (see
`PARIKA_Decision_Flow.md` section 4.4: "Planner cannot construct a
concrete, provider-specific request payload itself"). These types are
built by a `Goal.provider_request_builder` supplied by the caller
(typically an Interface session) and consumed only by
`OllamaProviderDriver`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from parika.core.provider_manager.request import ProviderRequest

from .messages import OllamaMessage, OllamaToolSpec

DEFAULT_MAX_TOOL_ITERATIONS = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaChatRequest(ProviderRequest):
    """
    Request for the Ollama `/api/chat` endpoint.
    """

    messages: tuple[OllamaMessage, ...]
    """
    Conversation history, oldest first, ending with the newest user
    (or tool) message to respond to.
    """

    tools: tuple[OllamaToolSpec, ...] = ()
    """
    Capabilities advertised to the model as callable tools/functions.

    When the model requests one of these by name, the driver resolves
    the corresponding `capability_id` and invokes it through Brain
    (never bypassing Planner) before continuing the chat.
    """

    on_token: Callable[[str], None] | None = None
    """
    Optional callback invoked with each incrementally streamed
    content fragment as the model generates its final answer. When
    set, the driver requests a streamed response from Ollama;
    otherwise a single non-streamed response is requested.

    Callbacks are invoked synchronously, from within `execute()`,
    once per streamed chunk. They are not invoked for intermediate
    tool-calling turns, only for the model's final textual answer.
    """

    max_tool_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS
    """
    Maximum number of tool-calling round trips permitted before the
    driver raises `OllamaToolCallError` rather than looping forever.
    """

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaGenerateRequest(ProviderRequest):
    """
    Request for the Ollama `/api/generate` endpoint.

    Used for single-turn, promptable text generation without chat
    history or tool calling.
    """

    prompt: str
    """
    Prompt text to generate a completion for.
    """

    system: str | None = None
    """
    Optional system prompt.
    """

    on_token: Callable[[str], None] | None = None
    """
    Optional callback invoked with each incrementally streamed
    content fragment. When set, the driver requests a streamed
    response from Ollama; otherwise a single non-streamed response is
    requested.
    """
