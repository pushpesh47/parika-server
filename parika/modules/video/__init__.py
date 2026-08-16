"""
PARIKA Video Module package.

Integrates the Video Capability family (I/O, video-level
understanding, timeline/temporal analysis, object/motion/event/text/
document Capabilities, video comparison, and quality Capabilities)
into PARIKA through ModuleManager, CapabilityRegistry, and
ToolManager, building on top of the existing, unmodified OCR/Vision/
Document Modules rather than duplicating any of their implementations
-- see `engine.py`'s own docstring for the cross-module reuse
mechanism.
"""

from __future__ import annotations

from .exceptions import (
    VideoAnalysisError,
    VideoDecodeError,
    VideoDependencyUnavailableError,
    VideoError,
    VideoFrameExtractionError,
    VideoReadError,
)
from .manifest import (
    VIDEO_MODULE_ID,
    VIDEO_MODULE_VERSION,
    create_video_module,
    create_video_module_manifest,
)
from .module_driver import MODULE_HEALTH_COMPONENT_ID, VideoModuleDriver

__all__ = [
    "MODULE_HEALTH_COMPONENT_ID",
    "VIDEO_MODULE_ID",
    "VIDEO_MODULE_VERSION",
    "VideoAnalysisError",
    "VideoDecodeError",
    "VideoDependencyUnavailableError",
    "VideoError",
    "VideoFrameExtractionError",
    "VideoModuleDriver",
    "VideoReadError",
    "create_video_module",
    "create_video_module_manifest",
]
