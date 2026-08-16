"""
PARIKA Generation Module - Capability/Tool Id Constants

Every `image.*`/`video.*` generation capability and tool id this
Module registers, in one place, following the project's frozen
naming convention (capabilities: `<domain>.<verb>_<object>`; tools:
`tool.<domain>_<verb>_<object>`).

`video.generate`, `video.generate_from_image`, and `video.edit` live
in this Module rather than `parika.modules.video` (the existing
video-*understanding* Module) because they are a different capability
domain concern -- generation, not understanding -- that happens to
share the `video.` id prefix; see this Module's own manifest
docstring for the full rationale. Registering them under a different
Python package than `parika.modules.video` has no bearing on the
capability id namespace, exactly as the existing Video Module already
demonstrates by registering its own Provider Capabilities under
`CapabilityCategory.VISION` (a different category than its own
domain) without any naming inconsistency.
"""

from __future__ import annotations

IMAGE_GENERATE_CAPABILITY_ID = "image.generate"
IMAGE_GENERATE_PROVIDER_CAPABILITY_ID = "image.provider_generate"
IMAGE_GENERATE_TOOL_ID = "tool.image_generate"

IMAGE_EDIT_CAPABILITY_ID = "image.edit"
IMAGE_EDIT_PROVIDER_CAPABILITY_ID = "image.provider_edit"
IMAGE_EDIT_TOOL_ID = "tool.image_edit"

VIDEO_GENERATE_CAPABILITY_ID = "video.generate"
VIDEO_GENERATE_PROVIDER_CAPABILITY_ID = "video.provider_generate"
VIDEO_GENERATE_TOOL_ID = "tool.video_generate"

VIDEO_GENERATE_FROM_IMAGE_CAPABILITY_ID = "video.generate_from_image"
VIDEO_GENERATE_FROM_IMAGE_PROVIDER_CAPABILITY_ID = (
    "video.provider_generate_from_image"
)
VIDEO_GENERATE_FROM_IMAGE_TOOL_ID = "tool.video_generate_from_image"

VIDEO_EDIT_CAPABILITY_ID = "video.edit"
VIDEO_EDIT_PROVIDER_CAPABILITY_ID = "video.provider_edit"
VIDEO_EDIT_TOOL_ID = "tool.video_edit"
