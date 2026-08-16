"""
PARIKA Video Module - ToolDriver Factory

`build_tool_drivers()` constructs one dedicated ToolDriver instance
per `module_driver._VIDEO_TOOL_SPECS` entry, keyed by its
`tool_capability_id` -- split out of `module_driver.py` purely to
keep that file within the project's File Size Guidelines, exactly
like `parika/modules/vision/extended_tool_drivers.py`'s own
precedent. Pure construction, no registration logic and no algorithm
of its own.
"""

from __future__ import annotations

from typing import Any, Callable

from parika.core.brain.brain import Brain
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressReporter

from .config import VideoToolConfig
from .driver_compare_videos import VideoCompareVideosToolDriver
from .driver_documents import (
    VideoDetectDocumentsToolDriver,
    VideoDetectSlidesToolDriver,
    VideoExtractTablesToolDriver,
)
from .driver_events import VideoDetectActionsToolDriver, VideoDetectEventsToolDriver
from .driver_io import (
    VideoFrameExtractionToolDriver,
    VideoKeyframeToolDriver,
    VideoMetadataToolDriver,
    VideoReadToolDriver,
    VideoThumbnailToolDriver,
)
from .driver_motion import VideoCompareFramesToolDriver, VideoDetectMotionToolDriver
from .driver_objects import (
    VideoCountObjectsToolDriver,
    VideoDetectObjectsToolDriver,
    VideoTrackObjectsToolDriver,
)
from .driver_quality import (
    VideoDetectBlackFramesToolDriver,
    VideoDetectBlurToolDriver,
    VideoDetectCorruptionToolDriver,
    VideoDetectRotationToolDriver,
)
from .driver_text import VideoExtractTextToolDriver
from .driver_timeline import (
    VideoDetectKeyMomentsToolDriver,
    VideoDetectSceneChangesToolDriver,
    VideoDetectShotsToolDriver,
    VideoGenerateTimelineToolDriver,
    VideoSegmentToolDriver,
)
from .driver_understanding import (
    VideoClassifyToolDriver,
    VideoUnderstandingSpec,
    VideoUnderstandingToolDriver,
)
from .video_capability_ids import (
    ANSWER_QUESTION_CAPABILITY_ID,
    ANSWER_QUESTION_PROVIDER_CAPABILITY_ID,
    CLASSIFY_VIDEO_CAPABILITY_ID,
    CLASSIFY_VIDEO_PROVIDER_CAPABILITY_ID,
    COMPARE_FRAMES_CAPABILITY_ID,
    COMPARE_VIDEOS_CAPABILITY_ID,
    COUNT_OBJECTS_CAPABILITY_ID,
    DESCRIBE_VIDEO_CAPABILITY_ID,
    DESCRIBE_VIDEO_PROVIDER_CAPABILITY_ID,
    DETECT_ACTIONS_CAPABILITY_ID,
    DETECT_ACTIONS_PROVIDER_CAPABILITY_ID,
    DETECT_BLACK_FRAMES_CAPABILITY_ID,
    DETECT_BLUR_CAPABILITY_ID,
    DETECT_CORRUPTION_CAPABILITY_ID,
    DETECT_DOCUMENTS_CAPABILITY_ID,
    DETECT_EVENTS_CAPABILITY_ID,
    DETECT_KEY_MOMENTS_CAPABILITY_ID,
    DETECT_KEY_MOMENTS_PROVIDER_CAPABILITY_ID,
    DETECT_MOTION_CAPABILITY_ID,
    DETECT_OBJECTS_CAPABILITY_ID,
    DETECT_ROTATION_CAPABILITY_ID,
    DETECT_SCENE_CHANGES_CAPABILITY_ID,
    DETECT_SHOTS_CAPABILITY_ID,
    DETECT_SLIDES_CAPABILITY_ID,
    EXTRACT_FRAMES_CAPABILITY_ID,
    EXTRACT_KEYFRAMES_CAPABILITY_ID,
    EXTRACT_METADATA_CAPABILITY_ID,
    EXTRACT_TABLES_CAPABILITY_ID,
    EXTRACT_TEXT_CAPABILITY_ID,
    EXTRACT_THUMBNAILS_CAPABILITY_ID,
    GENERATE_TIMELINE_CAPABILITY_ID,
    READ_VIDEO_CAPABILITY_ID,
    SEGMENT_VIDEO_CAPABILITY_ID,
    SUMMARIZE_VIDEO_CAPABILITY_ID,
    SUMMARIZE_VIDEO_PROVIDER_CAPABILITY_ID,
    TRACK_OBJECTS_CAPABILITY_ID,
)


def build_tool_drivers(
    *,
    brain: Brain,
    tool_manager: ToolManager,
    config: VideoToolConfig,
    progress_for: Callable[[str], ProgressReporter | None],
) -> dict[str, Any]:
    """Construct one dedicated ToolDriver instance per `video.*` TOOL Capability, keyed by its id."""

    return {
        READ_VIDEO_CAPABILITY_ID: VideoReadToolDriver(
            brain=brain, progress_reporter=progress_for(READ_VIDEO_CAPABILITY_ID)
        ),
        EXTRACT_METADATA_CAPABILITY_ID: VideoMetadataToolDriver(
            brain=brain,
            tool_manager=tool_manager,
            progress_reporter=progress_for(EXTRACT_METADATA_CAPABILITY_ID),
        ),
        EXTRACT_FRAMES_CAPABILITY_ID: VideoFrameExtractionToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(EXTRACT_FRAMES_CAPABILITY_ID)
        ),
        EXTRACT_KEYFRAMES_CAPABILITY_ID: VideoKeyframeToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(EXTRACT_KEYFRAMES_CAPABILITY_ID)
        ),
        EXTRACT_THUMBNAILS_CAPABILITY_ID: VideoThumbnailToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(EXTRACT_THUMBNAILS_CAPABILITY_ID)
        ),
        DESCRIBE_VIDEO_CAPABILITY_ID: VideoUnderstandingToolDriver(
            brain=brain,
            spec=VideoUnderstandingSpec(
                provider_capability_id=DESCRIBE_VIDEO_PROVIDER_CAPABILITY_ID,
                default_instruction=(
                    "Describe this video in detail: what it shows, notable "
                    "subjects, and how the content evolves over time."
                ),
                frame_count_attribute="describe_frame_count",
            ),
            config=config,
            progress_reporter=progress_for(DESCRIBE_VIDEO_CAPABILITY_ID),
        ),
        SUMMARIZE_VIDEO_CAPABILITY_ID: VideoUnderstandingToolDriver(
            brain=brain,
            spec=VideoUnderstandingSpec(
                provider_capability_id=SUMMARIZE_VIDEO_PROVIDER_CAPABILITY_ID,
                default_instruction=(
                    "Summarize this video concisely: its key scenes, "
                    "important events, and overall narrative arc."
                ),
                frame_count_attribute="summarize_frame_count",
            ),
            config=config,
            progress_reporter=progress_for(SUMMARIZE_VIDEO_CAPABILITY_ID),
        ),
        ANSWER_QUESTION_CAPABILITY_ID: VideoUnderstandingToolDriver(
            brain=brain,
            spec=VideoUnderstandingSpec(
                provider_capability_id=ANSWER_QUESTION_PROVIDER_CAPABILITY_ID,
                default_instruction="",
                question_argument=True,
                frame_count_attribute="answer_question_frame_count",
            ),
            config=config,
            progress_reporter=progress_for(ANSWER_QUESTION_CAPABILITY_ID),
        ),
        CLASSIFY_VIDEO_CAPABILITY_ID: VideoClassifyToolDriver(
            brain=brain,
            provider_capability_id=CLASSIFY_VIDEO_PROVIDER_CAPABILITY_ID,
            config=config,
            progress_reporter=progress_for(CLASSIFY_VIDEO_CAPABILITY_ID),
        ),
        GENERATE_TIMELINE_CAPABILITY_ID: VideoGenerateTimelineToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(GENERATE_TIMELINE_CAPABILITY_ID)
        ),
        DETECT_SCENE_CHANGES_CAPABILITY_ID: VideoDetectSceneChangesToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_SCENE_CHANGES_CAPABILITY_ID)
        ),
        DETECT_SHOTS_CAPABILITY_ID: VideoDetectShotsToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_SHOTS_CAPABILITY_ID)
        ),
        SEGMENT_VIDEO_CAPABILITY_ID: VideoSegmentToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(SEGMENT_VIDEO_CAPABILITY_ID)
        ),
        DETECT_KEY_MOMENTS_CAPABILITY_ID: VideoDetectKeyMomentsToolDriver(
            brain=brain,
            provider_capability_id=DETECT_KEY_MOMENTS_PROVIDER_CAPABILITY_ID,
            config=config,
            progress_reporter=progress_for(DETECT_KEY_MOMENTS_CAPABILITY_ID),
        ),
        DETECT_OBJECTS_CAPABILITY_ID: VideoDetectObjectsToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_OBJECTS_CAPABILITY_ID)
        ),
        COUNT_OBJECTS_CAPABILITY_ID: VideoCountObjectsToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(COUNT_OBJECTS_CAPABILITY_ID)
        ),
        TRACK_OBJECTS_CAPABILITY_ID: VideoTrackObjectsToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(TRACK_OBJECTS_CAPABILITY_ID)
        ),
        DETECT_MOTION_CAPABILITY_ID: VideoDetectMotionToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_MOTION_CAPABILITY_ID)
        ),
        COMPARE_FRAMES_CAPABILITY_ID: VideoCompareFramesToolDriver(
            brain=brain, progress_reporter=progress_for(COMPARE_FRAMES_CAPABILITY_ID)
        ),
        DETECT_EVENTS_CAPABILITY_ID: VideoDetectEventsToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_EVENTS_CAPABILITY_ID)
        ),
        DETECT_ACTIONS_CAPABILITY_ID: VideoDetectActionsToolDriver(
            brain=brain,
            provider_capability_id=DETECT_ACTIONS_PROVIDER_CAPABILITY_ID,
            config=config,
            progress_reporter=progress_for(DETECT_ACTIONS_CAPABILITY_ID),
        ),
        EXTRACT_TEXT_CAPABILITY_ID: VideoExtractTextToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(EXTRACT_TEXT_CAPABILITY_ID)
        ),
        DETECT_DOCUMENTS_CAPABILITY_ID: VideoDetectDocumentsToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_DOCUMENTS_CAPABILITY_ID)
        ),
        DETECT_SLIDES_CAPABILITY_ID: VideoDetectSlidesToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_SLIDES_CAPABILITY_ID)
        ),
        EXTRACT_TABLES_CAPABILITY_ID: VideoExtractTablesToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(EXTRACT_TABLES_CAPABILITY_ID)
        ),
        COMPARE_VIDEOS_CAPABILITY_ID: VideoCompareVideosToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(COMPARE_VIDEOS_CAPABILITY_ID)
        ),
        DETECT_BLUR_CAPABILITY_ID: VideoDetectBlurToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_BLUR_CAPABILITY_ID)
        ),
        DETECT_BLACK_FRAMES_CAPABILITY_ID: VideoDetectBlackFramesToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_BLACK_FRAMES_CAPABILITY_ID)
        ),
        DETECT_ROTATION_CAPABILITY_ID: VideoDetectRotationToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_ROTATION_CAPABILITY_ID)
        ),
        DETECT_CORRUPTION_CAPABILITY_ID: VideoDetectCorruptionToolDriver(
            brain=brain, config=config, progress_reporter=progress_for(DETECT_CORRUPTION_CAPABILITY_ID)
        ),
    }
