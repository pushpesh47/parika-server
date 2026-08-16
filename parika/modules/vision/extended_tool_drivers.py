"""
PARIKA Vision Module - Extended (Phase 1-5) ToolDriver Factory

`build_extended_tool_drivers()` constructs one dedicated ToolDriver
instance per `extended_tool_specs._VISION_EXTENDED_TOOL_SPECS` entry,
keyed by its `tool_capability_id` -- the factory
`VisionModuleDriver.__init__()` calls, split out purely to keep
`module_driver.py` within the project's File Size Guidelines. Pure
construction, no registration logic and no algorithm of its own --
see each driver class's own module for that.
"""

from __future__ import annotations

from typing import Any, Callable

from parika.core.brain.brain import Brain
from parika.core.utilities.progress import ProgressReporter

from .config import VisionToolConfig
from .driver_collection import (
    VisionFindDuplicatesToolDriver,
    VisionFindSimilarImagesToolDriver,
    VisionSearchImagesToolDriver,
)
from .driver_compare import (
    VisionCompareImagesToolDriver,
    VisionDetectDifferencesToolDriver,
)
from .driver_counting import (
    VisionClassifyImageToolDriver,
    VisionCountObjectsToolDriver,
)
from .driver_detection import (
    VisionDetectBarcodesToolDriver,
    VisionDetectFacesToolDriver,
    VisionDetectQrCodesToolDriver,
)
from .driver_editing import (
    VisionCompressImageToolDriver,
    VisionConvertFormatToolDriver,
    VisionCropImageToolDriver,
    VisionEnhanceImageToolDriver,
    VisionFlipImageToolDriver,
    VisionRemoveBackgroundToolDriver,
    VisionResizeImageToolDriver,
    VisionRotateImageToolDriver,
)
from .driver_quality import (
    VisionAnalyzeImageQualityToolDriver,
    VisionDetectAnomaliesToolDriver,
    VisionDetectBlurToolDriver,
    VisionDetectRotationToolDriver,
)
from .extended_tool_specs import (
    ANALYZE_IMAGE_QUALITY_CAPABILITY_ID,
    ANALYZE_IMAGE_QUALITY_PROVIDER_CAPABILITY_ID,
    CLASSIFY_IMAGE_CAPABILITY_ID,
    CLASSIFY_IMAGE_PROVIDER_CAPABILITY_ID,
    COMPARE_IMAGES_CAPABILITY_ID,
    COMPARE_IMAGES_PROVIDER_CAPABILITY_ID,
    COMPRESS_IMAGE_CAPABILITY_ID,
    CONVERT_FORMAT_CAPABILITY_ID,
    COUNT_OBJECTS_CAPABILITY_ID,
    COUNT_OBJECTS_PROVIDER_CAPABILITY_ID,
    CROP_IMAGE_CAPABILITY_ID,
    DETECT_ANOMALIES_CAPABILITY_ID,
    DETECT_ANOMALIES_PROVIDER_CAPABILITY_ID,
    DETECT_BARCODES_CAPABILITY_ID,
    DETECT_BARCODES_PROVIDER_CAPABILITY_ID,
    DETECT_BLUR_CAPABILITY_ID,
    DETECT_BLUR_PROVIDER_CAPABILITY_ID,
    DETECT_DIFFERENCES_CAPABILITY_ID,
    DETECT_DIFFERENCES_PROVIDER_CAPABILITY_ID,
    DETECT_FACES_CAPABILITY_ID,
    DETECT_FACES_PROVIDER_CAPABILITY_ID,
    DETECT_QR_CODES_CAPABILITY_ID,
    DETECT_QR_CODES_PROVIDER_CAPABILITY_ID,
    DETECT_ROTATION_CAPABILITY_ID,
    DETECT_ROTATION_PROVIDER_CAPABILITY_ID,
    ENHANCE_IMAGE_CAPABILITY_ID,
    ENHANCE_IMAGE_PROVIDER_CAPABILITY_ID,
    FIND_DUPLICATES_CAPABILITY_ID,
    FIND_DUPLICATES_PROVIDER_CAPABILITY_ID,
    FIND_SIMILAR_IMAGES_CAPABILITY_ID,
    FIND_SIMILAR_IMAGES_PROVIDER_CAPABILITY_ID,
    FLIP_IMAGE_CAPABILITY_ID,
    REMOVE_BACKGROUND_CAPABILITY_ID,
    REMOVE_BACKGROUND_PROVIDER_CAPABILITY_ID,
    RESIZE_IMAGE_CAPABILITY_ID,
    ROTATE_IMAGE_CAPABILITY_ID,
    SEARCH_IMAGES_CAPABILITY_ID,
    SEARCH_IMAGES_PROVIDER_CAPABILITY_ID,
)


def build_extended_tool_drivers(
    *,
    brain: Brain,
    progress_for: Callable[[str], ProgressReporter | None],
    vision_config: VisionToolConfig,
) -> dict[str, Any]:
    """
    Construct one dedicated ToolDriver instance per
    `extended_tool_specs._VISION_EXTENDED_TOOL_SPECS` entry, keyed by
    its `tool_capability_id`. `progress_for` mirrors
    `VisionModuleDriver`'s own `_progress_for()` closure (build a
    `ProgressReporter` bound to a Capability id, or `None` without an
    `EventBus`); `vision_config` supplies the handful of tunable
    settings a few of these Capabilities need
    (`max_search_candidates`, `duplicate_hamming_distance`,
    `jpeg_compress_quality`).
    """

    return {
        COMPARE_IMAGES_CAPABILITY_ID: VisionCompareImagesToolDriver(
            brain=brain,
            provider_capability_id=COMPARE_IMAGES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(COMPARE_IMAGES_CAPABILITY_ID),
        ),
        DETECT_DIFFERENCES_CAPABILITY_ID: VisionDetectDifferencesToolDriver(
            brain=brain,
            provider_capability_id=DETECT_DIFFERENCES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(DETECT_DIFFERENCES_CAPABILITY_ID),
        ),
        COUNT_OBJECTS_CAPABILITY_ID: VisionCountObjectsToolDriver(
            brain=brain,
            provider_capability_id=COUNT_OBJECTS_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(COUNT_OBJECTS_CAPABILITY_ID),
        ),
        CLASSIFY_IMAGE_CAPABILITY_ID: VisionClassifyImageToolDriver(
            brain=brain,
            provider_capability_id=CLASSIFY_IMAGE_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(CLASSIFY_IMAGE_CAPABILITY_ID),
        ),
        DETECT_FACES_CAPABILITY_ID: VisionDetectFacesToolDriver(
            brain=brain,
            provider_capability_id=DETECT_FACES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(DETECT_FACES_CAPABILITY_ID),
        ),
        DETECT_QR_CODES_CAPABILITY_ID: VisionDetectQrCodesToolDriver(
            brain=brain,
            provider_capability_id=DETECT_QR_CODES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(DETECT_QR_CODES_CAPABILITY_ID),
        ),
        DETECT_BARCODES_CAPABILITY_ID: VisionDetectBarcodesToolDriver(
            brain=brain,
            provider_capability_id=DETECT_BARCODES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(DETECT_BARCODES_CAPABILITY_ID),
        ),
        ANALYZE_IMAGE_QUALITY_CAPABILITY_ID: VisionAnalyzeImageQualityToolDriver(
            brain=brain,
            provider_capability_id=ANALYZE_IMAGE_QUALITY_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(ANALYZE_IMAGE_QUALITY_CAPABILITY_ID),
        ),
        DETECT_BLUR_CAPABILITY_ID: VisionDetectBlurToolDriver(
            brain=brain,
            provider_capability_id=DETECT_BLUR_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(DETECT_BLUR_CAPABILITY_ID),
        ),
        DETECT_ROTATION_CAPABILITY_ID: VisionDetectRotationToolDriver(
            brain=brain,
            provider_capability_id=DETECT_ROTATION_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(DETECT_ROTATION_CAPABILITY_ID),
        ),
        DETECT_ANOMALIES_CAPABILITY_ID: VisionDetectAnomaliesToolDriver(
            brain=brain,
            provider_capability_id=DETECT_ANOMALIES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(DETECT_ANOMALIES_CAPABILITY_ID),
        ),
        SEARCH_IMAGES_CAPABILITY_ID: VisionSearchImagesToolDriver(
            brain=brain,
            provider_capability_id=SEARCH_IMAGES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(SEARCH_IMAGES_CAPABILITY_ID),
            max_candidates=vision_config.max_search_candidates,
        ),
        FIND_SIMILAR_IMAGES_CAPABILITY_ID: VisionFindSimilarImagesToolDriver(
            brain=brain,
            provider_capability_id=FIND_SIMILAR_IMAGES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(FIND_SIMILAR_IMAGES_CAPABILITY_ID),
        ),
        FIND_DUPLICATES_CAPABILITY_ID: VisionFindDuplicatesToolDriver(
            brain=brain,
            provider_capability_id=FIND_DUPLICATES_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(FIND_DUPLICATES_CAPABILITY_ID),
            duplicate_hamming_distance=vision_config.duplicate_hamming_distance,
        ),
        CROP_IMAGE_CAPABILITY_ID: VisionCropImageToolDriver(
            brain=brain,
            progress_reporter=progress_for(CROP_IMAGE_CAPABILITY_ID),
        ),
        RESIZE_IMAGE_CAPABILITY_ID: VisionResizeImageToolDriver(
            brain=brain,
            progress_reporter=progress_for(RESIZE_IMAGE_CAPABILITY_ID),
        ),
        ROTATE_IMAGE_CAPABILITY_ID: VisionRotateImageToolDriver(
            brain=brain,
            progress_reporter=progress_for(ROTATE_IMAGE_CAPABILITY_ID),
        ),
        FLIP_IMAGE_CAPABILITY_ID: VisionFlipImageToolDriver(
            brain=brain,
            progress_reporter=progress_for(FLIP_IMAGE_CAPABILITY_ID),
        ),
        ENHANCE_IMAGE_CAPABILITY_ID: VisionEnhanceImageToolDriver(
            brain=brain,
            provider_capability_id=ENHANCE_IMAGE_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(ENHANCE_IMAGE_CAPABILITY_ID),
        ),
        REMOVE_BACKGROUND_CAPABILITY_ID: VisionRemoveBackgroundToolDriver(
            brain=brain,
            provider_capability_id=REMOVE_BACKGROUND_PROVIDER_CAPABILITY_ID,
            progress_reporter=progress_for(REMOVE_BACKGROUND_CAPABILITY_ID),
        ),
        CONVERT_FORMAT_CAPABILITY_ID: VisionConvertFormatToolDriver(
            brain=brain,
            progress_reporter=progress_for(CONVERT_FORMAT_CAPABILITY_ID),
        ),
        COMPRESS_IMAGE_CAPABILITY_ID: VisionCompressImageToolDriver(
            brain=brain,
            progress_reporter=progress_for(COMPRESS_IMAGE_CAPABILITY_ID),
            default_quality=vision_config.jpeg_compress_quality,
        ),
    }
