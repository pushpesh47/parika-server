"""
PARIKA Core - ProviderManager Component

Defines the provider-independent generation request type.

`GenerationRequest` is the generic analogue of a concrete generation
provider's own workflow request (e.g. a ComfyUI-specific workflow
payload): it carries only the semantic generation intent every
generation-capable provider needs -- what operation is being
requested, a text prompt, optional reference media, and optional
sizing/duration/seed hints -- with no provider-specific wire concept
(no workflow graphs, node ids, checkpoints, samplers, or queue
mechanics). Modules build this type via a Goal's
`provider_request_builder`; the Provider selected by Planner converts
it into its own concrete request at the provider boundary
(`ProviderDriver.execute()`), exactly like every other
`ProviderRequest` subtype (see `ChatRequest` for the established
pattern this type mirrors).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .request import ProviderRequest


class GenerationOperation(StrEnum):
    """
    Semantic generation operation a `GenerationRequest` represents.

    Deliberately a closed, provider-independent vocabulary of *what
    the caller wants*, not *how any specific provider does it*. A
    Provider maps each operation (together with the selected
    `ProviderModel`) to its own internal workflow/pipeline.
    """

    IMAGE_GENERATE = "image_generate"
    IMAGE_EDIT = "image_edit"
    VIDEO_GENERATE = "video_generate"
    VIDEO_GENERATE_FROM_IMAGE = "video_generate_from_image"
    VIDEO_EDIT = "video_edit"


@dataclass(frozen=True, slots=True, kw_only=True)
class GenerationRequest(ProviderRequest):
    """
    Provider-independent request for one generative media operation.

    Attributes:
        operation:
            The semantic generation operation requested.

        prompt:
            Text description of the desired result (or of the desired
            transformation, for edit operations).

        negative_prompt:
            Optional text describing what to avoid in the result.
            Providers with no concept of a negative prompt simply
            ignore it.

        input_images:
            Base64-encoded reference media attached to this request,
            in the same provider-independent shape as
            `ChatMessage.images`:

            - `image_edit`: exactly one source image to edit.
            - `video_generate_from_image`: exactly one starting image
              to animate.
            - `video_edit`: one or more ordered frames of the source
              video to transform.

            Empty for `image_generate` and `video_generate`.

        width / height:
            Optional requested output dimensions in pixels. `None`
            lets the provider choose a sensible default.

        duration_seconds:
            Optional requested output duration, for video operations.
            Ignored for image operations.

        fps:
            Optional requested output frame rate, for video
            operations. Ignored for image operations.

        seed:
            Optional deterministic seed. `None` lets the provider
            choose one (typically at random).
    """

    operation: GenerationOperation
    prompt: str = ""
    negative_prompt: str = ""
    input_images: tuple[str, ...] = ()
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_images", tuple(self.input_images))
