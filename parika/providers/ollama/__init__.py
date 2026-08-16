"""
PARIKA Ollama Provider.

Implements the `ProviderDriver` contract against a local or remote
Ollama server, with support for model discovery, health checks,
single-turn generation, multi-turn chat, native tool calling (resolved
through Brain), and token streaming.
"""

from .driver import OllamaProviderDriver
from .exceptions import (
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaProviderError,
    OllamaRequestError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaToolCallError,
)
from .manifest import OLLAMA_PROVIDER_ID, create_ollama_provider
from .messages import OllamaMessage, OllamaToolCall, OllamaToolSpec
from .requests import OllamaChatRequest, OllamaGenerateRequest
from .responses import OllamaChatResponse, OllamaGenerateResponse, OllamaToolInvocation
from .transport import OllamaTransport, UrllibOllamaTransport

__all__ = [
    "OLLAMA_PROVIDER_ID",
    "OllamaChatRequest",
    "OllamaChatResponse",
    "OllamaConnectionError",
    "OllamaGenerateRequest",
    "OllamaGenerateResponse",
    "OllamaMessage",
    "OllamaModelNotFoundError",
    "OllamaProviderDriver",
    "OllamaProviderError",
    "OllamaRequestError",
    "OllamaResponseError",
    "OllamaTimeoutError",
    "OllamaToolCall",
    "OllamaToolCallError",
    "OllamaToolInvocation",
    "OllamaToolSpec",
    "OllamaTransport",
    "UrllibOllamaTransport",
    "create_ollama_provider",
]
