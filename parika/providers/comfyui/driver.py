"""
PARIKA ComfyUI Provider - Driver

Implements the `ProviderDriver` contract
(`parika.core.provider_manager.driver.ProviderDriver`) against a local
or remote ComfyUI server (https://github.com/comfyanonymous/ComfyUI):
model discovery (`GET /models/diffusion_models`), health checks
(`GET /system_stats`), and generation (`POST /prompt` +
`GET /history/{id}` polling + `GET /view` output retrieval), for the
five generation operations `GenerationOperation` declares.

Workflow construction is delegated to `workflows.py`, model/filename
mapping to `model_config.py`, and model discovery to `discovery.py`,
so this module stays focused on orchestration -- exactly the same
split `parika.providers.ollama.driver` already establishes for the
Ollama provider (see that module's own docstring).

This driver contains no registration, lifecycle, or capability-
routing logic; that is owned by `ProviderManager` and whatever
composition root registers this provider (see
`parika/interfaces/runtime.py`).
"""

from __future__ import annotations

import base64
import mimetypes
import random
import time
import uuid
from typing import Any

from parika.core.logger.logger import Logger
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.generation_request import (
    GenerationOperation,
    GenerationRequest,
)
from parika.core.provider_manager.generation_result import (
    GeneratedArtifact,
    GenerationResult,
)
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse

from . import workflows
from .discovery import discover_models as _discover_models
from .discovery import model_listing_path_for_loader as _model_listing_path_for_loader
from .exceptions import (
    ComfyUIOutputNotFoundError,
    ComfyUIProviderError,
    ComfyUIRequestError,
    ComfyUITimeoutError,
    ComfyUIWorkflowError,
)
from .model_config import VIDEO_VACE_MODEL_ID, ComfyUIModelConfig
from .transport import ComfyUITransport

DEFAULT_BASE_URL = "http://127.0.0.1:8188"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_POLL_TIMEOUT_SECONDS = 900.0

DEFAULT_IMAGE_WIDTH = 768
DEFAULT_IMAGE_HEIGHT = 768
DEFAULT_VIDEO_WIDTH = 832
DEFAULT_VIDEO_HEIGHT = 480
DEFAULT_VIDEO_DURATION_SECONDS = 3.0
DEFAULT_VIDEO_FPS = 16.0

_DIFFUSION_MODELS_PATH = "/models/diffusion_models"
_SYSTEM_STATS_PATH = "/system_stats"
_PROMPT_PATH = "/prompt"
_HISTORY_PATH = "/history"
_UPLOAD_PATH = "/upload/image"
_VIEW_PATH = "/view"


class ComfyUIProviderDriver(ProviderDriver):
    """
    ProviderDriver implementation for a local or remote ComfyUI
    server.
    """

    def __init__(
        self,
        *,
        transport: ComfyUITransport,
        logger: Logger,
        base_url: str = DEFAULT_BASE_URL,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        model_config: ComfyUIModelConfig | None = None,
    ) -> None:
        """
        Initialize the driver.

        Args:
            transport:
                HTTP transport used to communicate with the ComfyUI
                server.

            logger:
                PARIKA Logger component.

            base_url:
                Base URL of the ComfyUI server, with no trailing
                slash. Read from Configuration by the composition
                root; never hardcoded by callers.

            connect_timeout_seconds:
                Timeout applied to lightweight calls (model discovery,
                health checks, workflow submission).

            request_timeout_seconds:
                Timeout applied to output-retrieval calls (`/view`).

            poll_interval_seconds:
                Delay between successive `/history` polls while a
                generation is in progress.

            poll_timeout_seconds:
                Maximum total time to wait for a generation to
                complete before raising `ComfyUITimeoutError`.
                Generation (especially video) can take substantially
                longer than an ordinary request; this is deliberately
                much larger than `request_timeout_seconds`.

            model_config:
                This provider's model/filename mapping. Defaults to
                `ComfyUIModelConfig()`, whose own defaults match the
                models discovered on the reference development
                installation; the composition root normally overrides
                this from `Configuration`.
        """

        self._transport = transport
        self._logger = logger.get_logger(__name__)

        self._base_url = base_url.rstrip("/")
        self._connect_timeout_seconds = connect_timeout_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds
        self._model_config = model_config or ComfyUIModelConfig()

    # ------------------------------------------------------------------
    # ProviderDriver contract
    # ------------------------------------------------------------------

    def discover_models(self) -> frozenset[ProviderModel]:
        """
        Discover which of this provider's models are actually usable,
        by checking ComfyUI's own installed model listings.

        Always checks `_DIFFUSION_MODELS_PATH` (needed for the image
        model and any video model configured with `video_*_loader=
        "native"`). Additionally checks whichever listing
        `discovery.model_listing_path_for_loader()` resolves for
        `"gguf"`, but only if a video model is actually configured
        with `video_*_loader="gguf"` -- a native-only configuration
        (today's only behavior) makes exactly the one HTTP call it
        always has. If that additional listing cannot be fetched
        (e.g. ComfyUI-GGUF is not installed, so its `unet_gguf`
        folder was never registered), the GGUF-configured model is
        simply treated as not installed rather than failing model
        discovery entirely -- consistent with this provider's
        existing "not installed -> not offered" discovery philosophy
        for every other model.

        Returns a tuple through this `frozenset`-typed signature --
        see `discovery.discover_models()`'s own docstring for why.
        """

        payload = self._request_json(
            "GET",
            _DIFFUSION_MODELS_PATH,
            payload=None,
            timeout=self._connect_timeout_seconds,
        )
        installed_diffusion_models = payload if isinstance(payload, list) else []

        installed_gguf_models: list[Any] = []
        configured_loaders = {
            self._model_config.video_t2v_loader,
            self._model_config.video_vace_loader,
        }

        if "gguf" in configured_loaders:
            gguf_path = _model_listing_path_for_loader("gguf")

            try:
                gguf_payload = self._request_json(
                    "GET",
                    gguf_path,
                    payload=None,
                    timeout=self._connect_timeout_seconds,
                )
                installed_gguf_models = (
                    gguf_payload if isinstance(gguf_payload, list) else []
                )

            except ComfyUIProviderError as ex:
                self._logger.warning(
                    "Could not list GGUF models at '%s' (%s). "
                    "ComfyUI-GGUF may not be installed; any video "
                    "model configured with loader='gguf' will be "
                    "treated as not installed until it is.",
                    gguf_path,
                    ex,
                )

        return _discover_models(  # type: ignore[return-value]
            installed_diffusion_models=installed_diffusion_models,
            installed_gguf_models=installed_gguf_models,
            model_config=self._model_config,
        )

    def check_health(self) -> ProviderHealth:
        """
        Check whether the ComfyUI server is reachable.
        """

        started_at = time.perf_counter()

        try:
            payload = self._request_json(
                "GET",
                _SYSTEM_STATS_PATH,
                payload=None,
                timeout=self._connect_timeout_seconds,
            )

        except ComfyUIProviderError as ex:
            return ProviderHealth(available=False, message=str(ex))

        latency_ms = (time.perf_counter() - started_at) * 1000
        version = (
            payload.get("system", {}).get("comfyui_version")
            if isinstance(payload, dict)
            else None
        )
        message = f"ComfyUI {version}" if version else "ComfyUI reachable"

        return ProviderHealth(available=True, latency_ms=latency_ms, message=message)

    def execute(
        self,
        model: ProviderModel,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """
        Execute a `GenerationRequest` using the specified ComfyUI
        model.

        Dispatches by `request.operation`, builds the corresponding
        ComfyUI workflow (`workflows.py`), submits it, polls for
        completion, retrieves the produced artifact(s), and returns a
        provider-independent `GenerationResult` -- never exposing
        ComfyUI's workflow JSON, node ids, or history/queue payloads.

        Raises:
            ComfyUIRequestError:
                If `request` is not a `GenerationRequest`, or the
                selected `model` cannot perform the requested
                operation.
        """

        if not isinstance(request, GenerationRequest):
            raise ComfyUIRequestError(
                "ComfyUIProviderDriver only supports GenerationRequest, "
                f"got {type(request).__name__!r}."
            )

        handlers = {
            GenerationOperation.IMAGE_GENERATE: self._generate_image,
            GenerationOperation.IMAGE_EDIT: self._edit_image,
            GenerationOperation.VIDEO_GENERATE: self._generate_video,
            GenerationOperation.VIDEO_GENERATE_FROM_IMAGE: (
                self._generate_video_from_image
            ),
            GenerationOperation.VIDEO_EDIT: self._edit_video,
        }

        handler = handlers.get(request.operation)

        if handler is None:
            raise ComfyUIRequestError(
                f"ComfyUIProviderDriver does not support operation "
                f"{request.operation!r}."
            )

        return handler(model, request)

    # ------------------------------------------------------------------
    # Operation handlers
    # ------------------------------------------------------------------

    def _generate_image(
        self, model: ProviderModel, request: GenerationRequest
    ) -> GenerationResult:
        graph, output_node_id = workflows.build_image_generate_workflow(
            model_config=self._model_config,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            width=request.width or DEFAULT_IMAGE_WIDTH,
            height=request.height or DEFAULT_IMAGE_HEIGHT,
            seed=self._resolve_seed(request.seed),
        )

        return self._run_and_collect(model, graph, output_node_id)

    def _edit_image(
        self, model: ProviderModel, request: GenerationRequest
    ) -> GenerationResult:
        if not request.input_images:
            raise ComfyUIRequestError(
                "image_edit requires exactly one input image in "
                "GenerationRequest.input_images."
            )

        input_image_name = self._upload_image_base64(
            request.input_images[0], suffix="image_edit"
        )

        graph, output_node_id = workflows.build_image_edit_workflow(
            model_config=self._model_config,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            seed=self._resolve_seed(request.seed),
            input_image_name=input_image_name,
        )

        return self._run_and_collect(model, graph, output_node_id)

    def _generate_video(
        self, model: ProviderModel, request: GenerationRequest
    ) -> GenerationResult:
        diffusion_model = self._model_config.diffusion_model_for(model.id)

        if diffusion_model is None:
            raise ComfyUIRequestError(
                f"ComfyUI model '{model.id}' is not one this provider "
                "recognizes for video_generate."
            )

        weight_dtype = self._model_config.weight_dtype_for(model.id) or "default"
        loader = self._model_config.loader_for(model.id) or "native"

        fps = request.fps or DEFAULT_VIDEO_FPS
        graph, output_node_id = workflows.build_video_generate_workflow(
            model_config=self._model_config,
            diffusion_model=diffusion_model,
            weight_dtype=weight_dtype,
            loader=loader,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            width=request.width or DEFAULT_VIDEO_WIDTH,
            height=request.height or DEFAULT_VIDEO_HEIGHT,
            length=self._resolve_length(request.duration_seconds, fps),
            fps=fps,
            seed=self._resolve_seed(request.seed),
        )

        return self._run_and_collect(model, graph, output_node_id)

    def _generate_video_from_image(
        self, model: ProviderModel, request: GenerationRequest
    ) -> GenerationResult:
        self._require_vace_model(model, operation="video_generate_from_image")

        if not request.input_images:
            raise ComfyUIRequestError(
                "video_generate_from_image requires exactly one "
                "starting image in GenerationRequest.input_images."
            )

        reference_image_name = self._upload_image_base64(
            request.input_images[0], suffix="video_i2v"
        )

        fps = request.fps or DEFAULT_VIDEO_FPS
        graph, output_node_id = workflows.build_video_generate_from_image_workflow(
            model_config=self._model_config,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            width=request.width or DEFAULT_VIDEO_WIDTH,
            height=request.height or DEFAULT_VIDEO_HEIGHT,
            length=self._resolve_length(request.duration_seconds, fps),
            fps=fps,
            seed=self._resolve_seed(request.seed),
            reference_image_name=reference_image_name,
        )

        return self._run_and_collect(model, graph, output_node_id)

    def _edit_video(
        self, model: ProviderModel, request: GenerationRequest
    ) -> GenerationResult:
        self._require_vace_model(model, operation="video_edit")

        if not request.input_images:
            raise ComfyUIRequestError(
                "video_edit requires the source video's frames in "
                "GenerationRequest.input_images."
            )

        control_video_name = self._upload_video_base64(
            request.input_images[0], suffix="video_edit"
        )

        fps = request.fps or DEFAULT_VIDEO_FPS
        graph, output_node_id = workflows.build_video_edit_workflow(
            model_config=self._model_config,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            width=request.width or DEFAULT_VIDEO_WIDTH,
            height=request.height or DEFAULT_VIDEO_HEIGHT,
            length=self._resolve_length(request.duration_seconds, fps),
            fps=fps,
            seed=self._resolve_seed(request.seed),
            control_video_name=control_video_name,
        )

        return self._run_and_collect(model, graph, output_node_id)

    def _require_vace_model(self, model: ProviderModel, *, operation: str) -> None:
        if model.id != VIDEO_VACE_MODEL_ID:
            raise ComfyUIRequestError(
                f"ComfyUI model '{model.id}' does not support "
                f"{operation}; only the VACE model "
                f"('{VIDEO_VACE_MODEL_ID}') supports image/video "
                "conditioning."
            )

    # ------------------------------------------------------------------
    # Workflow submission, polling, and output retrieval
    # ------------------------------------------------------------------

    def _run_and_collect(
        self,
        model: ProviderModel,
        graph: workflows.WorkflowGraph,
        output_node_id: str,
    ) -> GenerationResult:
        prompt_id = self._submit(graph)
        outputs = self._await_completion(prompt_id)
        artifact = self._collect_artifact(outputs, output_node_id)

        return GenerationResult(model_id=model.id, artifacts=(artifact,))

    def _submit(self, graph: workflows.WorkflowGraph) -> str:
        response = self._request_json(
            "POST",
            _PROMPT_PATH,
            payload={"prompt": graph, "client_id": uuid.uuid4().hex},
            timeout=self._connect_timeout_seconds,
        )

        node_errors = response.get("node_errors") if isinstance(response, dict) else None

        if node_errors:
            raise ComfyUIWorkflowError(
                f"ComfyUI rejected the submitted workflow: {node_errors!r}"
            )

        prompt_id = response.get("prompt_id") if isinstance(response, dict) else None

        if not isinstance(prompt_id, str) or not prompt_id:
            raise ComfyUIWorkflowError(
                "ComfyUI's /prompt response did not include a prompt_id: "
                f"{response!r}"
            )

        return prompt_id

    def _await_completion(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._poll_timeout_seconds

        while True:
            history = self._request_json(
                "GET",
                f"{_HISTORY_PATH}/{prompt_id}",
                payload=None,
                timeout=self._connect_timeout_seconds,
            )

            entry = history.get(prompt_id) if isinstance(history, dict) else None

            if isinstance(entry, dict):
                status = entry.get("status", {})

                if isinstance(status, dict):
                    if status.get("status_str") == "error":
                        raise ComfyUIWorkflowError(
                            "ComfyUI reported an execution error for "
                            f"prompt '{prompt_id}': {status!r}"
                        )

                    if status.get("completed"):
                        outputs = entry.get("outputs")

                        if isinstance(outputs, dict):
                            return outputs

            if time.monotonic() >= deadline:
                raise ComfyUITimeoutError(
                    f"ComfyUI generation for prompt '{prompt_id}' did not "
                    f"complete within {self._poll_timeout_seconds} seconds."
                )

            time.sleep(self._poll_interval_seconds)

    def _collect_artifact(
        self,
        outputs: dict[str, Any],
        output_node_id: str,
    ) -> GeneratedArtifact:
        node_output = outputs.get(output_node_id)
        images = node_output.get("images") if isinstance(node_output, dict) else None

        if not isinstance(images, list) or not images:
            raise ComfyUIOutputNotFoundError(
                f"ComfyUI's output node '{output_node_id}' produced no "
                f"usable artifact: {node_output!r}"
            )

        first = images[0]

        if not isinstance(first, dict) or "filename" not in first:
            raise ComfyUIOutputNotFoundError(
                f"ComfyUI's output node '{output_node_id}' produced a "
                f"malformed artifact reference: {first!r}"
            )

        filename = str(first["filename"])
        subfolder = str(first.get("subfolder", ""))
        file_type = str(first.get("type", "output"))

        content = self._transport.fetch_binary(
            self._view_url(filename=filename, subfolder=subfolder, file_type=file_type),
            timeout=self._request_timeout_seconds,
        )

        mime_type, _ = mimetypes.guess_type(filename)

        return GeneratedArtifact(
            content_base64=base64.b64encode(content).decode("ascii"),
            mime_type=mime_type or "application/octet-stream",
        )

    # ------------------------------------------------------------------
    # Input media upload
    # ------------------------------------------------------------------

    def _upload_image_base64(self, image_base64: str, *, suffix: str) -> str:
        content = base64.b64decode(image_base64)
        filename = f"parika_{suffix}_{uuid.uuid4().hex}.png"
        response = self._transport.upload_media(
            f"{self._base_url}{_UPLOAD_PATH}",
            filename,
            content,
            timeout=self._request_timeout_seconds,
        )

        return str(response.get("name", filename))

    def _upload_video_base64(self, video_base64: str, *, suffix: str) -> str:
        content = base64.b64decode(video_base64)
        filename = f"parika_{suffix}_{uuid.uuid4().hex}.mp4"
        response = self._transport.upload_media(
            f"{self._base_url}{_UPLOAD_PATH}",
            filename,
            content,
            timeout=self._request_timeout_seconds,
        )

        return str(response.get("name", filename))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_seed(self, seed: int | None) -> int:
        return seed if seed is not None else random.randint(0, 2**32 - 1)

    def _resolve_length(self, duration_seconds: float | None, fps: float) -> int:
        """
        Convert a requested duration into a Wan/VACE-compatible frame
        count (`1 + 4k`, matching `WanVaceToVideo`'s own `length`
        parameter grid).
        """

        duration = duration_seconds or DEFAULT_VIDEO_DURATION_SECONDS
        raw_frames = max(1, round(duration * fps))
        steps = max(0, round((raw_frames - 1) / 4))

        return 1 + 4 * steps

    def _view_url(self, *, filename: str, subfolder: str, file_type: str) -> str:
        from urllib.parse import urlencode

        query = urlencode(
            {"filename": filename, "subfolder": subfolder, "type": file_type}
        )

        return f"{self._base_url}{_VIEW_PATH}?{query}"

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> Any:
        return self._transport.request_json(
            method,
            f"{self._base_url}{path}",
            payload=payload,
            timeout=timeout,
        )
