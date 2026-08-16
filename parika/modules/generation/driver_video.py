"""
PARIKA Generation Module - Video ToolDrivers

Implements `video.generate`, `video.generate_from_image`, and
`video.edit`: orchestrator ToolDrivers following exactly the same
shape as `driver_image.py`'s image drivers -- obtain any input image/
video through `filesystem.read`, delegate to this Module's own
Provider-backed Capability, write the produced artifact back out
through `filesystem.write`. No ComfyUI-specific concept exists here.
"""

from __future__ import annotations

from uuid import uuid4

from parika.core.provider_manager.generation_request import GenerationOperation
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine
from .config import GenerationToolConfig
from .exceptions import GenerationInputReadError


def _require_prompt(request: ToolRequest) -> str:
    prompt = str(request.arguments.get("prompt", "")).strip()

    if not prompt:
        raise GenerationInputReadError(
            "request.arguments['prompt'] must be a non-empty string."
        )

    return prompt


def _default_output_path(output_directory: str, *, prefix: str) -> str:
    return f"{output_directory}/{prefix}_{uuid4().hex}.mp4"


def _numeric(request: ToolRequest, key: str, cast):
    value = request.arguments.get(key)
    return cast(value) if value is not None else None


class VideoGenerateToolDriver:
    """`ToolDriver` implementing `video.generate`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        config: GenerationToolConfig,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._config = config
        self._progress = progress_reporter or NullProgressReporter(
            "video.generate"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        prompt = _require_prompt(request)
        negative_prompt = str(request.arguments.get("negative_prompt", ""))
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(
                self._config.output_directory, prefix="video_generate"
            )
        )

        self._progress.started(message="Generating video...")

        result = engine.generate_with_provider(
            self._brain,
            self._provider_capability_id,
            operation=GenerationOperation.VIDEO_GENERATE,
            task_category="video_generation",
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=_numeric(request, "width", int),
            height=_numeric(request, "height", int),
            duration_seconds=_numeric(request, "duration_seconds", float),
            fps=_numeric(request, "fps", float),
            seed=_numeric(request, "seed", int),
            execution_requirements=request.metadata.get("execution_requirements"),
        )

        artifact = result.artifacts[0]

        self._progress.progress(message="Writing video...")
        engine.write_file_base64(self._brain, output_path, artifact.content_base64)

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"output_path": output_path}, attributes={"prompt": prompt})


class VideoGenerateFromImageToolDriver:
    """`ToolDriver` implementing `video.generate_from_image`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        config: GenerationToolConfig,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._config = config
        self._progress = progress_reporter or NullProgressReporter(
            "video.generate_from_image"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise GenerationInputReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        instruction = str(request.arguments.get("instruction", "")).strip()
        negative_prompt = str(request.arguments.get("negative_prompt", ""))
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(
                self._config.output_directory, prefix="video_generate_from_image"
            )
        )

        self._progress.started(message="Reading image...")
        image_base64 = engine.read_file_base64(self._brain, path)

        self._progress.progress(message="Generating video...")
        result = engine.generate_with_provider(
            self._brain,
            self._provider_capability_id,
            operation=GenerationOperation.VIDEO_GENERATE_FROM_IMAGE,
            task_category="video_generation_from_image",
            prompt=instruction,
            negative_prompt=negative_prompt,
            input_images=(image_base64,),
            width=_numeric(request, "width", int),
            height=_numeric(request, "height", int),
            duration_seconds=_numeric(request, "duration_seconds", float),
            fps=_numeric(request, "fps", float),
            seed=_numeric(request, "seed", int),
            execution_requirements=request.metadata.get("execution_requirements"),
        )

        artifact = result.artifacts[0]

        self._progress.progress(message="Writing video...")
        engine.write_file_base64(self._brain, output_path, artifact.content_base64)

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"output_path": output_path}, attributes={"path": path})


class VideoEditToolDriver:
    """`ToolDriver` implementing `video.edit`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        config: GenerationToolConfig,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.edit")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise GenerationInputReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        instruction = _require_prompt(request)
        negative_prompt = str(request.arguments.get("negative_prompt", ""))
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(
                self._config.output_directory, prefix="video_edit"
            )
        )

        self._progress.started(message="Reading video...")
        video_base64 = engine.read_file_base64(self._brain, path)

        self._progress.progress(message="Editing video...")
        result = engine.generate_with_provider(
            self._brain,
            self._provider_capability_id,
            operation=GenerationOperation.VIDEO_EDIT,
            task_category="video_editing",
            prompt=instruction,
            negative_prompt=negative_prompt,
            input_images=(video_base64,),
            width=_numeric(request, "width", int),
            height=_numeric(request, "height", int),
            duration_seconds=_numeric(request, "duration_seconds", float),
            fps=_numeric(request, "fps", float),
            seed=_numeric(request, "seed", int),
            execution_requirements=request.metadata.get("execution_requirements"),
        )

        artifact = result.artifacts[0]

        self._progress.progress(message="Writing video...")
        engine.write_file_base64(self._brain, output_path, artifact.content_base64)

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"output_path": output_path}, attributes={"path": path})
