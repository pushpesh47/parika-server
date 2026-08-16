"""
PARIKA Video Module - Manifest

Defines the static ModuleManifest describing the Video Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .module_driver import VideoModuleDriver

VIDEO_MODULE_ID = "video"
VIDEO_MODULE_VERSION = "1.0.0"


def create_video_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Video Module.
    """

    return ModuleManifest(
        id=VIDEO_MODULE_ID,
        name="Video",
        version=VIDEO_MODULE_VERSION,
        description=(
            "Registers the video understanding family: I/O and "
            "deterministic metadata/frame/keyframe/thumbnail "
            "extraction (`video.read_video`, `video.extract_metadata`, "
            "`video.extract_frames`, `video.extract_keyframes`, "
            "`video.extract_thumbnails`); video-level understanding "
            "(`video.describe_video`, `video.summarize_video`, "
            "`video.answer_question`, `video.classify_video`) built on "
            "adaptive frame sampling plus a Provider-backed video-"
            "capable model; deterministic timeline/temporal "
            "Capabilities (`video.generate_timeline`, "
            "`video.detect_scene_changes`, `video.detect_shots`, "
            "`video.segment_video`, `video.detect_key_moments`); "
            "object understanding that reuses Vision's own "
            "`vision.provider_detect_objects` Capability directly "
            "(`video.detect_objects`, `video.count_objects`, "
            "`video.track_objects`); deterministic motion analysis "
            "(`video.detect_motion`, `video.compare_frames`); event/"
            "action analysis (`video.detect_events`, "
            "`video.detect_actions`); text extraction reusing OCR's "
            "own `ocr.provider_extract_text` Capability directly "
            "(`video.extract_text`); document/slide/table Capabilities "
            "(`video.detect_documents`, `video.detect_slides`, "
            "`video.extract_tables`); video comparison "
            "(`video.compare_videos`); and deterministic quality "
            "Capabilities (`video.detect_blur`, "
            "`video.detect_black_frames`, `video.detect_rotation`, "
            "`video.detect_corruption`). Builds on top of the "
            "existing, unmodified OCR/Vision/Document Modules rather "
            "than duplicating any of their implementations -- see "
            "`engine.py`'s own docstring for the cross-module reuse "
            "mechanism."
        ),
        author="PARIKA",
        license="MIT",
        tags=("video", "vision", "temporal"),
        driver="parika.modules.video.module_driver.VideoModuleDriver",
    )


def create_video_module(driver: VideoModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Video Module.

    Args:
        driver:
            Constructed VideoModuleDriver instance for this module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=VIDEO_MODULE_ID,
        manifest=create_video_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
