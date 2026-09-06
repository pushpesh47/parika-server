from typing import Any
from parika.core.provider_manager.exceptions import (
    ProviderAuthenticationError, ProviderAuthorizationError, ProviderCapabilityError,
    ProviderConnectionError, ProviderConfigurationError, ProviderExecutionError,
    ProviderModelNotFoundError, ProviderRateLimitError, ProviderResponseError,
    ProviderServerError, ProviderTimeoutError,
)

class OpenAICompatibleError(ProviderExecutionError):
    """Base for sanitized errors from an OpenAI-compatible endpoint."""
class OpenAICompatibleAuthenticationError(OpenAICompatibleError, ProviderAuthenticationError): pass
class OpenAICompatibleAuthorizationError(OpenAICompatibleError, ProviderAuthorizationError): pass
class OpenAICompatibleRateLimitError(OpenAICompatibleError, ProviderRateLimitError): pass
class OpenAICompatibleConnectionError(OpenAICompatibleError, ProviderConnectionError): pass
class OpenAICompatibleTimeoutError(OpenAICompatibleError, ProviderTimeoutError): pass
class OpenAICompatibleModelNotFoundError(OpenAICompatibleError, ProviderModelNotFoundError): pass
class OpenAICompatibleCapabilityError(OpenAICompatibleError, ProviderCapabilityError): pass
class OpenAICompatibleResponseError(OpenAICompatibleError, ProviderResponseError):
    def __init__(
        self,
        message: str,
        *,
        response_body: Any = None,
        http_status: int | None = None,
    ):
        super().__init__(message)
        self.response_body = response_body
        self.http_status = http_status
class OpenAICompatibleServerError(OpenAICompatibleError, ProviderServerError): pass
class OpenAICompatibleConfigurationError(OpenAICompatibleError, ProviderConfigurationError): pass
