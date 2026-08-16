"""
PARIKA Generation Module - Image ToolDrivers

Implements `image.generate` and `image.edit`: orchestrator ToolDrivers
that obtain any input image through the existing `filesystem.read`
Capability, delegate the actual generation to this Module's own
Provider-backed Capability (`image.provider_generate`/
`image.provider_edit`, resolved by Planner's Model Selection Framework
to whichever compatible Provider is registered -- ComfyUI today), and
write the produced artifact back out through the existing
`filesystem.write` Capability -- exactly the same shape
`vision/driver_editing.py`'s hybrid drivers already establish.
Neither driver, nor this Module generally, ever constructs or
inspects a ComfyUI-specific type.
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


def _default_output_path(
    output_directory: str, *, prefix: str, extension: str
) -> str:
    return f"{output_directory}/{prefix}_{uuid4().hex}.{extension}"


class ImageGenerateToolDriver:
    """`ToolDriver` implementing `image.generate`."""

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
            "image.generate"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        prompt = _require_prompt(request)
        negative_prompt = str(request.arguments.get("negative_prompt", ""))
        width = request.arguments.get("width")
        height = request.arguments.get("height")
        seed = request.arguments.get("seed")

        self._progress.started(message="Generating image...")

        result = engine.generate_with_provider(
            self._brain,
            self._provider_capability_id,
            operation=GenerationOperation.IMAGE_GENERATE,
            task_category="image_generation",
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=int(width) if width is not None else None,
            height=int(height) if height is not None else None,
            seed=int(seed) if seed is not None else None,
            execution_requirements=request.metadata.get("execution_requirements"),
        )

        artifact = result.artifacts[0]
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(
                self._config.output_directory,
                prefix="image_generate",
                extension=engine.extension_for_mime_type(artifact.mime_type),
            )
        )

        self._progress.progress(message="Writing image...")
        engine.write_file_base64(self._brain, output_path, artifact.content_base64)

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"output_path": output_path},
            attributes={"prompt": prompt},
        )


class ImageEditToolDriver:
    """`ToolDriver` implementing `image.edit`."""

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
        self._progress = progress_reporter or NullProgressReporter("image.edit")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise GenerationInputReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        instruction = _require_prompt(request)
        negative_prompt = str(request.arguments.get("negative_prompt", ""))
        seed = request.arguments.get("seed")
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(
                self._config.output_directory,
                prefix="image_edit",
                extension="png",
            )
        )

        self._progress.started(message="Reading image...")
        image_base64 = engine.read_file_base64(self._brain, path)

        self._progress.progress(message="Editing image...")
        result = engine.generate_with_provider(
            self._brain,
            self._provider_capability_id,
            operation=GenerationOperation.IMAGE_EDIT,
            task_category="image_editing",
            prompt=instruction,
            negative_prompt=negative_prompt,
            input_images=(image_base64,),
            seed=int(seed) if seed is not None else None,
            execution_requirements=request.metadata.get("execution_requirements"),
        )

        artifact = result.artifacts[0]

        self._progress.progress(message="Writing image...")
        engine.write_file_base64(self._brain, output_path, artifact.content_base64)

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"output_path": output_path},
            attributes={"path": path},
        )
