"""
PARIKA ComfyUI Provider

Implements ComfyUI as a normal PARIKA `ProviderDriver`, satisfying
`image.provider_generate`, `image.provider_edit`,
`video.provider_generate`, `video.provider_generate_from_image`, and
`video.provider_edit` (see `parika.modules.generation`) by submitting
workflows to a local ComfyUI HTTP API, polling for completion, and
returning provider-independent `GenerationResult`s.

See `driver.py`'s module docstring for the full architecture, and
`workflows.py`'s module docstring for exactly which installed models
back which operation and why.
"""

from __future__ import annotations

from .driver import (
    DEFAULT_BASE_URL,
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ComfyUIProviderDriver,
)
from .exceptions import (
    ComfyUIConnectionError,
    ComfyUIModelNotFoundError,
    ComfyUIOutputNotFoundError,
    ComfyUIProviderError,
    ComfyUIRequestError,
    ComfyUIResponseError,
    ComfyUITimeoutError,
    ComfyUIWorkflowError,
)
from .manifest import COMFYUI_PROVIDER_ID, create_comfyui_provider
from .model_config import (
    IMAGE_MODEL_ID,
    VIDEO_T2V_MODEL_ID,
    VIDEO_VACE_MODEL_ID,
    ComfyUIModelConfig,
)
from .transport import ComfyUITransport, UrllibComfyUITransport

__all__ = [
    "COMFYUI_PROVIDER_ID",
    "DEFAULT_BASE_URL",
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_POLL_TIMEOUT_SECONDS",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "IMAGE_MODEL_ID",
    "VIDEO_T2V_MODEL_ID",
    "VIDEO_VACE_MODEL_ID",
    "ComfyUIConnectionError",
    "ComfyUIModelConfig",
    "ComfyUIModelNotFoundError",
    "ComfyUIOutputNotFoundError",
    "ComfyUIProviderDriver",
    "ComfyUIProviderError",
    "ComfyUIRequestError",
    "ComfyUIResponseError",
    "ComfyUITimeoutError",
    "ComfyUITransport",
    "ComfyUIWorkflowError",
    "UrllibComfyUITransport",
    "create_comfyui_provider",
]
