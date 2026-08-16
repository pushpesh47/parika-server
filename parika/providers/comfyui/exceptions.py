"""
PARIKA ComfyUI Provider Exceptions

Defines the exception hierarchy used by the ComfyUI provider driver.

Every exception raised by this package derives from
`ComfyUIProviderError`. Where an equivalent, more general
`ProviderError` subtype already exists on `ProviderManager`'s public
exception vocabulary (see `parika.core.provider_manager.exceptions`),
the corresponding ComfyUI exception also derives from it so that
callers written against the generic Provider contract keep working
unmodified -- exactly the dual-inheritance convention established by
`parika.providers.ollama.exceptions`. `ProviderManager.execute()` does
not wrap driver exceptions (by design), so these exceptions propagate
to `CapabilityExecutor`, which wraps them into
`CapabilityExecutionError` regardless of their concrete type.
"""

from __future__ import annotations

from parika.core.provider_manager.exceptions import (
    ProviderCapabilityError,
    ProviderConnectionError,
    ProviderExecutionError,
    ProviderModelNotFoundError,
    ProviderTimeoutError,
)


class ComfyUIProviderError(Exception):
    """
    Base exception for all ComfyUI provider errors.
    """


class ComfyUIConnectionError(ComfyUIProviderError, ProviderConnectionError):
    """
    Raised when the ComfyUI server cannot be reached.

    Covers both "ComfyUI is not installed / not running" and "the
    configured `base_url` is unreachable".
    """


class ComfyUITimeoutError(ComfyUIProviderError, ProviderTimeoutError):
    """
    Raised when a request to the ComfyUI server, or an in-progress
    generation being polled, exceeds its configured timeout.
    """


class ComfyUIModelNotFoundError(ComfyUIProviderError, ProviderModelNotFoundError):
    """
    Raised when a `ProviderModel` selected for this provider maps to a
    diffusion model file that is not actually installed on the
    ComfyUI server (per the live `/models/diffusion_models` listing).
    """


class ComfyUIResponseError(ComfyUIProviderError, ProviderExecutionError):
    """
    Raised when the ComfyUI server returns a malformed or unexpected
    response.
    """


class ComfyUIRequestError(ComfyUIProviderError, ProviderCapabilityError):
    """
    Raised when an unsupported or invalid request is supplied to the
    ComfyUI provider driver (e.g. a request type other than
    `GenerationRequest`, or an operation this provider/model
    combination cannot perform).
    """


class ComfyUIWorkflowError(ComfyUIProviderError, ProviderExecutionError):
    """
    Raised when ComfyUI rejects a submitted workflow (`node_errors` in
    the `/prompt` response) or reports an execution error while
    running it (`status.status_str == "error"` in `/history`).
    """


class ComfyUIOutputNotFoundError(ComfyUIProviderError, ProviderExecutionError):
    """
    Raised when a completed ComfyUI execution reports no usable output
    artifact (e.g. the expected output node produced no images/videos).
    """
