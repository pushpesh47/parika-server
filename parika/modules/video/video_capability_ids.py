"""
PARIKA Video Module - Capability/Tool Id Constants

Every `video.*` Capability id, its `tool.video_*` Tool id, and (for
the handful that need one) its internal `video.provider_*` Capability
id -- purely data, shared by `module_driver.py` and
`tool_driver_factory.py` so neither has to repeat these string
literals.
"""

from __future__ import annotations

READ_VIDEO_CAPABILITY_ID = "video.read_video"
READ_VIDEO_TOOL_ID = "tool.video_read_video"

EXTRACT_METADATA_CAPABILITY_ID = "video.extract_metadata"
EXTRACT_METADATA_TOOL_ID = "tool.video_extract_metadata"

EXTRACT_FRAMES_CAPABILITY_ID = "video.extract_frames"
EXTRACT_FRAMES_TOOL_ID = "tool.video_extract_frames"

EXTRACT_KEYFRAMES_CAPABILITY_ID = "video.extract_keyframes"
EXTRACT_KEYFRAMES_TOOL_ID = "tool.video_extract_keyframes"

EXTRACT_THUMBNAILS_CAPABILITY_ID = "video.extract_thumbnails"
EXTRACT_THUMBNAILS_TOOL_ID = "tool.video_extract_thumbnails"

DESCRIBE_VIDEO_CAPABILITY_ID = "video.describe_video"
DESCRIBE_VIDEO_PROVIDER_CAPABILITY_ID = "video.provider_describe_video"
DESCRIBE_VIDEO_TOOL_ID = "tool.video_describe_video"

SUMMARIZE_VIDEO_CAPABILITY_ID = "video.summarize_video"
SUMMARIZE_VIDEO_PROVIDER_CAPABILITY_ID = "video.provider_summarize_video"
SUMMARIZE_VIDEO_TOOL_ID = "tool.video_summarize_video"

ANSWER_QUESTION_CAPABILITY_ID = "video.answer_question"
ANSWER_QUESTION_PROVIDER_CAPABILITY_ID = "video.provider_answer_question"
ANSWER_QUESTION_TOOL_ID = "tool.video_answer_question"

CLASSIFY_VIDEO_CAPABILITY_ID = "video.classify_video"
CLASSIFY_VIDEO_PROVIDER_CAPABILITY_ID = "video.provider_classify_video"
CLASSIFY_VIDEO_TOOL_ID = "tool.video_classify_video"

GENERATE_TIMELINE_CAPABILITY_ID = "video.generate_timeline"
GENERATE_TIMELINE_TOOL_ID = "tool.video_generate_timeline"

DETECT_SCENE_CHANGES_CAPABILITY_ID = "video.detect_scene_changes"
DETECT_SCENE_CHANGES_TOOL_ID = "tool.video_detect_scene_changes"

DETECT_SHOTS_CAPABILITY_ID = "video.detect_shots"
DETECT_SHOTS_TOOL_ID = "tool.video_detect_shots"

SEGMENT_VIDEO_CAPABILITY_ID = "video.segment_video"
SEGMENT_VIDEO_TOOL_ID = "tool.video_segment_video"

DETECT_KEY_MOMENTS_CAPABILITY_ID = "video.detect_key_moments"
DETECT_KEY_MOMENTS_PROVIDER_CAPABILITY_ID = "video.provider_detect_key_moments"
DETECT_KEY_MOMENTS_TOOL_ID = "tool.video_detect_key_moments"

DETECT_OBJECTS_CAPABILITY_ID = "video.detect_objects"
DETECT_OBJECTS_TOOL_ID = "tool.video_detect_objects"

COUNT_OBJECTS_CAPABILITY_ID = "video.count_objects"
COUNT_OBJECTS_TOOL_ID = "tool.video_count_objects"

TRACK_OBJECTS_CAPABILITY_ID = "video.track_objects"
TRACK_OBJECTS_TOOL_ID = "tool.video_track_objects"

DETECT_MOTION_CAPABILITY_ID = "video.detect_motion"
DETECT_MOTION_TOOL_ID = "tool.video_detect_motion"

COMPARE_FRAMES_CAPABILITY_ID = "video.compare_frames"
COMPARE_FRAMES_TOOL_ID = "tool.video_compare_frames"

DETECT_EVENTS_CAPABILITY_ID = "video.detect_events"
DETECT_EVENTS_TOOL_ID = "tool.video_detect_events"

DETECT_ACTIONS_CAPABILITY_ID = "video.detect_actions"
DETECT_ACTIONS_PROVIDER_CAPABILITY_ID = "video.provider_detect_actions"
DETECT_ACTIONS_TOOL_ID = "tool.video_detect_actions"

EXTRACT_TEXT_CAPABILITY_ID = "video.extract_text"
EXTRACT_TEXT_TOOL_ID = "tool.video_extract_text"

DETECT_DOCUMENTS_CAPABILITY_ID = "video.detect_documents"
DETECT_DOCUMENTS_TOOL_ID = "tool.video_detect_documents"

DETECT_SLIDES_CAPABILITY_ID = "video.detect_slides"
DETECT_SLIDES_TOOL_ID = "tool.video_detect_slides"

EXTRACT_TABLES_CAPABILITY_ID = "video.extract_tables"
EXTRACT_TABLES_TOOL_ID = "tool.video_extract_tables"

COMPARE_VIDEOS_CAPABILITY_ID = "video.compare_videos"
COMPARE_VIDEOS_TOOL_ID = "tool.video_compare_videos"

DETECT_BLUR_CAPABILITY_ID = "video.detect_blur"
DETECT_BLUR_TOOL_ID = "tool.video_detect_blur"

DETECT_BLACK_FRAMES_CAPABILITY_ID = "video.detect_black_frames"
DETECT_BLACK_FRAMES_TOOL_ID = "tool.video_detect_black_frames"

DETECT_ROTATION_CAPABILITY_ID = "video.detect_rotation"
DETECT_ROTATION_TOOL_ID = "tool.video_detect_rotation"

DETECT_CORRUPTION_CAPABILITY_ID = "video.detect_corruption"
DETECT_CORRUPTION_TOOL_ID = "tool.video_detect_corruption"
