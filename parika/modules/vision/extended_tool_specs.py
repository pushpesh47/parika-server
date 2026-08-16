"""
PARIKA Vision Module - Extended (Phase 1-5) Tool Specs

Declares the 22 deterministic-first `vision.*` TOOL Capability/Tool
pairs (`_VisionExtendedToolSpec`/`_VISION_EXTENDED_TOOL_SPECS`) --
Phase 1-5 of the Vision extension. Purely data -- split out of
`module_driver.py` purely to keep that file within the project's File
Size Guidelines (`docs/architecture/PARIKA_Core_Coding_Standards.md`),
exactly the same reasoning `parika/modules/ocr/tool_affordances.py`
already documents for its own split. `VisionModuleDriver.start()`/
`stop()` (still in `module_driver.py`) register/unregister everything
declared here exactly like they always have; the per-Capability
ToolDriver instances themselves are built by
`extended_tool_drivers.build_extended_tool_drivers()`.

The two purely Provider-backed Phase 2/3 additions
(`vision.detect_logos`, `vision.reason_about_image`) are deliberately
*not* here -- they reuse `VisionToolDriver` unmodified via two more
`VisionToolSpec` entries in `module_driver.py`'s own `_VISION_TOOL_SPECS`,
since no classical algorithm applies to either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .tool_affordances_phase1 import (
    VISION_CLASSIFY_IMAGE_TOOL_AFFORDANCE,
    VISION_COMPARE_IMAGES_TOOL_AFFORDANCE,
    VISION_COUNT_OBJECTS_TOOL_AFFORDANCE,
    VISION_DETECT_DIFFERENCES_TOOL_AFFORDANCE,
)
from .tool_affordances_phase2 import (
    VISION_DETECT_BARCODES_TOOL_AFFORDANCE,
    VISION_DETECT_FACES_TOOL_AFFORDANCE,
    VISION_DETECT_QR_CODES_TOOL_AFFORDANCE,
)
from .tool_affordances_phase3 import (
    VISION_ANALYZE_IMAGE_QUALITY_TOOL_AFFORDANCE,
    VISION_DETECT_ANOMALIES_TOOL_AFFORDANCE,
    VISION_DETECT_BLUR_TOOL_AFFORDANCE,
    VISION_DETECT_ROTATION_TOOL_AFFORDANCE,
)
from .tool_affordances_phase4 import (
    VISION_FIND_DUPLICATES_TOOL_AFFORDANCE,
    VISION_FIND_SIMILAR_IMAGES_TOOL_AFFORDANCE,
    VISION_SEARCH_IMAGES_TOOL_AFFORDANCE,
)
from .tool_affordances_phase5 import (
    VISION_COMPRESS_IMAGE_TOOL_AFFORDANCE,
    VISION_CONVERT_FORMAT_TOOL_AFFORDANCE,
    VISION_CROP_IMAGE_TOOL_AFFORDANCE,
    VISION_ENHANCE_IMAGE_TOOL_AFFORDANCE,
    VISION_FLIP_IMAGE_TOOL_AFFORDANCE,
    VISION_REMOVE_BACKGROUND_TOOL_AFFORDANCE,
    VISION_RESIZE_IMAGE_TOOL_AFFORDANCE,
    VISION_ROTATE_IMAGE_TOOL_AFFORDANCE,
)

# Phase 1-4 deterministic-first Capability/Tool/Provider-Capability
# ids (each Capability owns a distinct `vision.provider_*` id per
# this Module's frozen naming convention -- see
# `_VisionExtendedToolSpec`'s own docstring).

COMPARE_IMAGES_CAPABILITY_ID = "vision.compare_images"
COMPARE_IMAGES_PROVIDER_CAPABILITY_ID = "vision.provider_compare_images"
COMPARE_IMAGES_TOOL_ID = "tool.vision_compare_images"

DETECT_DIFFERENCES_CAPABILITY_ID = "vision.detect_differences"
DETECT_DIFFERENCES_PROVIDER_CAPABILITY_ID = "vision.provider_detect_differences"
DETECT_DIFFERENCES_TOOL_ID = "tool.vision_detect_differences"

COUNT_OBJECTS_CAPABILITY_ID = "vision.count_objects"
COUNT_OBJECTS_PROVIDER_CAPABILITY_ID = "vision.provider_count_objects"
COUNT_OBJECTS_TOOL_ID = "tool.vision_count_objects"

CLASSIFY_IMAGE_CAPABILITY_ID = "vision.classify_image"
CLASSIFY_IMAGE_PROVIDER_CAPABILITY_ID = "vision.provider_classify_image"
CLASSIFY_IMAGE_TOOL_ID = "tool.vision_classify_image"

DETECT_FACES_CAPABILITY_ID = "vision.detect_faces"
DETECT_FACES_PROVIDER_CAPABILITY_ID = "vision.provider_detect_faces"
DETECT_FACES_TOOL_ID = "tool.vision_detect_faces"

DETECT_QR_CODES_CAPABILITY_ID = "vision.detect_qr_codes"
DETECT_QR_CODES_PROVIDER_CAPABILITY_ID = "vision.provider_detect_qr_codes"
DETECT_QR_CODES_TOOL_ID = "tool.vision_detect_qr_codes"

DETECT_BARCODES_CAPABILITY_ID = "vision.detect_barcodes"
DETECT_BARCODES_PROVIDER_CAPABILITY_ID = "vision.provider_detect_barcodes"
DETECT_BARCODES_TOOL_ID = "tool.vision_detect_barcodes"

ANALYZE_IMAGE_QUALITY_CAPABILITY_ID = "vision.analyze_image_quality"
ANALYZE_IMAGE_QUALITY_PROVIDER_CAPABILITY_ID = "vision.provider_analyze_image_quality"
ANALYZE_IMAGE_QUALITY_TOOL_ID = "tool.vision_analyze_image_quality"

DETECT_BLUR_CAPABILITY_ID = "vision.detect_blur"
DETECT_BLUR_PROVIDER_CAPABILITY_ID = "vision.provider_detect_blur"
DETECT_BLUR_TOOL_ID = "tool.vision_detect_blur"

DETECT_ROTATION_CAPABILITY_ID = "vision.detect_rotation"
DETECT_ROTATION_PROVIDER_CAPABILITY_ID = "vision.provider_detect_rotation"
DETECT_ROTATION_TOOL_ID = "tool.vision_detect_rotation"

DETECT_ANOMALIES_CAPABILITY_ID = "vision.detect_anomalies"
DETECT_ANOMALIES_PROVIDER_CAPABILITY_ID = "vision.provider_detect_anomalies"
DETECT_ANOMALIES_TOOL_ID = "tool.vision_detect_anomalies"

SEARCH_IMAGES_CAPABILITY_ID = "vision.search_images"
SEARCH_IMAGES_PROVIDER_CAPABILITY_ID = "vision.provider_search_images"
SEARCH_IMAGES_TOOL_ID = "tool.vision_search_images"

FIND_SIMILAR_IMAGES_CAPABILITY_ID = "vision.find_similar_images"
FIND_SIMILAR_IMAGES_PROVIDER_CAPABILITY_ID = "vision.provider_find_similar_images"
FIND_SIMILAR_IMAGES_TOOL_ID = "tool.vision_find_similar_images"

FIND_DUPLICATES_CAPABILITY_ID = "vision.find_duplicates"
FIND_DUPLICATES_PROVIDER_CAPABILITY_ID = "vision.provider_find_duplicates"
FIND_DUPLICATES_TOOL_ID = "tool.vision_find_duplicates"

# Phase 5 editing Capability/Tool ids. `crop_image`/`resize_image`/
# `rotate_image`/`flip_image`/`convert_format`/`compress_image` are
# purely deterministic -- no Provider Capability id at all, per the
# frozen naming convention (only `enhance_image`/`remove_background`
# have one).
CROP_IMAGE_CAPABILITY_ID = "vision.crop_image"
CROP_IMAGE_TOOL_ID = "tool.vision_crop_image"

RESIZE_IMAGE_CAPABILITY_ID = "vision.resize_image"
RESIZE_IMAGE_TOOL_ID = "tool.vision_resize_image"

ROTATE_IMAGE_CAPABILITY_ID = "vision.rotate_image"
ROTATE_IMAGE_TOOL_ID = "tool.vision_rotate_image"

FLIP_IMAGE_CAPABILITY_ID = "vision.flip_image"
FLIP_IMAGE_TOOL_ID = "tool.vision_flip_image"

ENHANCE_IMAGE_CAPABILITY_ID = "vision.enhance_image"
ENHANCE_IMAGE_PROVIDER_CAPABILITY_ID = "vision.provider_enhance_image"
ENHANCE_IMAGE_TOOL_ID = "tool.vision_enhance_image"

REMOVE_BACKGROUND_CAPABILITY_ID = "vision.remove_background"
REMOVE_BACKGROUND_PROVIDER_CAPABILITY_ID = "vision.provider_remove_background"
REMOVE_BACKGROUND_TOOL_ID = "tool.vision_remove_background"

CONVERT_FORMAT_CAPABILITY_ID = "vision.convert_format"
CONVERT_FORMAT_TOOL_ID = "tool.vision_convert_format"

COMPRESS_IMAGE_CAPABILITY_ID = "vision.compress_image"
COMPRESS_IMAGE_TOOL_ID = "tool.vision_compress_image"


@dataclass(frozen=True, slots=True, kw_only=True)
class _VisionExtendedToolSpec:
    """
    Immutable declaration of one deterministic-first `vision.*` TOOL
    Capability/Tool pair, each backed by its own dedicated ToolDriver
    (`driver_compare.py`/`driver_counting.py`/`driver_detection.py`/
    `driver_quality.py`/`driver_collection.py`/`driver_editing.py`)
    rather than the shared `VisionToolDriver` -- because, unlike the
    purely Provider-backed Capabilities in `_VISION_TOOL_SPECS`, each
    of these first runs its own deterministic algorithm. Mirrors
    `_OcrExtendedToolSpec` (`parika/modules/ocr/module_driver.py`)
    exactly, extended with an *optional* `provider_capability_id`
    since -- unlike OCR's extended Capabilities, which either need no
    Provider Capability at all or share the one `ocr.provider_extract_text`
    -- this Module's frozen naming convention gives each new
    Capability its own distinct `vision.provider_*` Capability (used
    only for the opt-in semantic-narration escalation each ToolDriver's
    own docstring describes), except the six purely deterministic
    Phase 5 editing Capabilities, which register none at all.
    """

    tool_capability_id: str
    tool_id: str
    name: str
    tool_description: str
    tool_affordance: Mapping[str, Any]
    provider_capability_id: str | None = None
    provider_description: str | None = None


_VISION_EXTENDED_TOOL_SPECS: tuple[_VisionExtendedToolSpec, ...] = (
    _VisionExtendedToolSpec(
        tool_capability_id=COMPARE_IMAGES_CAPABILITY_ID,
        tool_id=COMPARE_IMAGES_TOOL_ID,
        name="Vision - Compare Images",
        tool_description=(
            "Deterministically measures similarity between two local "
            "images (perceptual-hash/pixel/histogram); optionally "
            "asks a Vision model to explain the result."
        ),
        tool_affordance=VISION_COMPARE_IMAGES_TOOL_AFFORDANCE,
        provider_capability_id=COMPARE_IMAGES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic explanation of an image comparison, "
            "satisfied by a Provider model specialized for vision "
            "understanding. Only consulted when the caller explicitly "
            "asks for an explanation; the similarity metrics "
            "themselves are always computed deterministically."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=DETECT_DIFFERENCES_CAPABILITY_ID,
        tool_id=DETECT_DIFFERENCES_TOOL_ID,
        name="Vision - Detect Differences",
        tool_description=(
            "Deterministically locates the differing pixel regions "
            "between two local images; optionally asks a Vision model "
            "to explain the result."
        ),
        tool_affordance=VISION_DETECT_DIFFERENCES_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_DIFFERENCES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic explanation of located image "
            "differences, satisfied by a Provider model specialized "
            "for vision understanding. Only consulted when the "
            "caller explicitly asks for an explanation."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=COUNT_OBJECTS_CAPABILITY_ID,
        tool_id=COUNT_OBJECTS_TOOL_ID,
        name="Vision - Count Objects",
        tool_description=(
            "Counts objects in a local image, preferring a free "
            "deterministic blob count and falling back to a Vision "
            "model for named/cluttered cases."
        ),
        tool_affordance=VISION_COUNT_OBJECTS_TOOL_AFFORDANCE,
        provider_capability_id=COUNT_OBJECTS_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven object counting, satisfied by a Provider model "
            "specialized for vision understanding. Only consulted "
            "when the deterministic blob count is not confident or a "
            "specific object type is named."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=CLASSIFY_IMAGE_CAPABILITY_ID,
        tool_id=CLASSIFY_IMAGE_TOOL_ID,
        name="Vision - Classify Image",
        tool_description=(
            "Classifies a local image, preferring a free deterministic "
            "coarse image-type heuristic and falling back to a Vision "
            "model when open-set candidate labels are supplied."
        ),
        tool_affordance=VISION_CLASSIFY_IMAGE_TOOL_AFFORDANCE,
        provider_capability_id=CLASSIFY_IMAGE_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven open-set image classification, satisfied by a "
            "Provider model specialized for vision understanding. "
            "Only consulted when the caller supplies candidate labels."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=DETECT_FACES_CAPABILITY_ID,
        tool_id=DETECT_FACES_TOOL_ID,
        name="Vision - Detect Faces",
        tool_description=(
            "Deterministically detects human faces (Haar cascade) in "
            "a local image; optionally asks a Vision model to narrate "
            "the result."
        ),
        tool_affordance=VISION_DETECT_FACES_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_FACES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic narration on top of deterministic "
            "face detections, satisfied by a Provider model "
            "specialized for vision understanding. Only consulted "
            "when the caller explicitly asks for a narration."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=DETECT_QR_CODES_CAPABILITY_ID,
        tool_id=DETECT_QR_CODES_TOOL_ID,
        name="Vision - Detect QR Codes",
        tool_description=(
            "Deterministically decodes QR codes (ZBar) in a local "
            "image; optionally asks a Vision model to narrate the "
            "result."
        ),
        tool_affordance=VISION_DETECT_QR_CODES_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_QR_CODES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic narration on top of deterministically "
            "decoded QR codes, satisfied by a Provider model "
            "specialized for vision understanding. Only consulted "
            "when the caller explicitly asks for a narration."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=DETECT_BARCODES_CAPABILITY_ID,
        tool_id=DETECT_BARCODES_TOOL_ID,
        name="Vision - Detect Barcodes",
        tool_description=(
            "Deterministically decodes 1D/2D barcodes (ZBar) in a "
            "local image; optionally asks a Vision model to narrate "
            "the result."
        ),
        tool_affordance=VISION_DETECT_BARCODES_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_BARCODES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic narration on top of deterministically "
            "decoded barcodes, satisfied by a Provider model "
            "specialized for vision understanding. Only consulted "
            "when the caller explicitly asks for a narration."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=ANALYZE_IMAGE_QUALITY_CAPABILITY_ID,
        tool_id=ANALYZE_IMAGE_QUALITY_TOOL_ID,
        name="Vision - Analyze Image Quality",
        tool_description=(
            "Deterministically assesses a local image's technical "
            "quality (resolution/sharpness/contrast); optionally asks "
            "a Vision model to explain the result."
        ),
        tool_affordance=VISION_ANALYZE_IMAGE_QUALITY_TOOL_AFFORDANCE,
        provider_capability_id=ANALYZE_IMAGE_QUALITY_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic explanation of a deterministic image "
            "quality assessment, satisfied by a Provider model "
            "specialized for vision understanding. Only consulted "
            "when the caller explicitly asks for an explanation."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=DETECT_BLUR_CAPABILITY_ID,
        tool_id=DETECT_BLUR_TOOL_ID,
        name="Vision - Detect Blur",
        tool_description=(
            "Deterministically measures a local image's sharpness "
            "(variance of Laplacian); optionally asks a Vision model "
            "to explain the result."
        ),
        tool_affordance=VISION_DETECT_BLUR_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_BLUR_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic explanation of a deterministic blur "
            "measurement, satisfied by a Provider model specialized "
            "for vision understanding. Only consulted when the "
            "caller explicitly asks for an explanation."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=DETECT_ROTATION_CAPABILITY_ID,
        tool_id=DETECT_ROTATION_TOOL_ID,
        name="Vision - Detect Rotation",
        tool_description=(
            "Deterministically estimates a local image's likely "
            "rotation; optionally asks a Vision model to explain the "
            "result."
        ),
        tool_affordance=VISION_DETECT_ROTATION_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_ROTATION_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic explanation of a deterministic "
            "rotation estimate, satisfied by a Provider model "
            "specialized for vision understanding. Only consulted "
            "when the caller explicitly asks for an explanation."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=DETECT_ANOMALIES_CAPABILITY_ID,
        tool_id=DETECT_ANOMALIES_TOOL_ID,
        name="Vision - Detect Anomalies",
        tool_description=(
            "Deterministically flags statistically unusual regions of "
            "a local image; optionally asks a Vision model to "
            "semantically explain the result."
        ),
        tool_affordance=VISION_DETECT_ANOMALIES_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_ANOMALIES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic anomaly interpretation on top of a "
            "deterministic statistical-outlier scan, satisfied by a "
            "Provider model specialized for vision understanding. "
            "Only consulted when the caller explicitly asks for an "
            "explanation."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=SEARCH_IMAGES_CAPABILITY_ID,
        tool_id=SEARCH_IMAGES_TOOL_ID,
        name="Vision - Search Images",
        tool_description=(
            "Searches a bounded set of local images for ones matching "
            "a natural-language query, via a Vision model per "
            "candidate (capped by max_candidates)."
        ),
        tool_affordance=VISION_SEARCH_IMAGES_TOOL_AFFORDANCE,
        provider_capability_id=SEARCH_IMAGES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven per-image semantic search matching, satisfied "
            "by a Provider model specialized for vision understanding. "
            "Genuinely semantic -- no deterministic algorithm can "
            "recognize open-ended image content."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=FIND_SIMILAR_IMAGES_CAPABILITY_ID,
        tool_id=FIND_SIMILAR_IMAGES_TOOL_ID,
        name="Vision - Find Similar Images",
        tool_description=(
            "Deterministically ranks a set of local images by "
            "perceptual similarity to a reference image; optionally "
            "asks a Vision model to explain the top match."
        ),
        tool_affordance=VISION_FIND_SIMILAR_IMAGES_TOOL_AFFORDANCE,
        provider_capability_id=FIND_SIMILAR_IMAGES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic explanation of the top deterministic "
            "similarity match, satisfied by a Provider model "
            "specialized for vision understanding. Only consulted "
            "when the caller sets verify_with_model."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=FIND_DUPLICATES_CAPABILITY_ID,
        tool_id=FIND_DUPLICATES_TOOL_ID,
        name="Vision - Find Duplicates",
        tool_description=(
            "Deterministically groups a set of local images into "
            "near-duplicate clusters; optionally asks a Vision model "
            "to confirm the top group."
        ),
        tool_affordance=VISION_FIND_DUPLICATES_TOOL_AFFORDANCE,
        provider_capability_id=FIND_DUPLICATES_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven semantic confirmation of the top deterministic "
            "duplicate group, satisfied by a Provider model "
            "specialized for vision understanding. Only consulted "
            "when the caller sets verify_with_model."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=CROP_IMAGE_CAPABILITY_ID,
        tool_id=CROP_IMAGE_TOOL_ID,
        name="Vision - Crop Image",
        tool_description="Deterministically crops a local image to a pixel rectangle and writes the result.",
        tool_affordance=VISION_CROP_IMAGE_TOOL_AFFORDANCE,
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=RESIZE_IMAGE_CAPABILITY_ID,
        tool_id=RESIZE_IMAGE_TOOL_ID,
        name="Vision - Resize Image",
        tool_description="Deterministically resizes a local image and writes the result.",
        tool_affordance=VISION_RESIZE_IMAGE_TOOL_AFFORDANCE,
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=ROTATE_IMAGE_CAPABILITY_ID,
        tool_id=ROTATE_IMAGE_TOOL_ID,
        name="Vision - Rotate Image",
        tool_description="Deterministically rotates a local image by an arbitrary angle and writes the result.",
        tool_affordance=VISION_ROTATE_IMAGE_TOOL_AFFORDANCE,
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=FLIP_IMAGE_CAPABILITY_ID,
        tool_id=FLIP_IMAGE_TOOL_ID,
        name="Vision - Flip Image",
        tool_description="Deterministically mirrors a local image horizontally or vertically and writes the result.",
        tool_affordance=VISION_FLIP_IMAGE_TOOL_AFFORDANCE,
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=ENHANCE_IMAGE_CAPABILITY_ID,
        tool_id=ENHANCE_IMAGE_TOOL_ID,
        name="Vision - Enhance Image",
        tool_description=(
            "Deterministically enhances a local image (auto-contrast/"
            "sharpen/denoise) and writes the result; optionally asks "
            "a Vision model for further suggestions."
        ),
        tool_affordance=VISION_ENHANCE_IMAGE_TOOL_AFFORDANCE,
        provider_capability_id=ENHANCE_IMAGE_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven enhancement suggestions on top of a "
            "deterministic enhancement pipeline, satisfied by a "
            "Provider model specialized for vision understanding. "
            "Only consulted when the caller supplies an instruction; "
            "never used to alter the deterministic pixels themselves."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=REMOVE_BACKGROUND_CAPABILITY_ID,
        tool_id=REMOVE_BACKGROUND_TOOL_ID,
        name="Vision - Remove Background",
        tool_description=(
            "Deterministically removes a local image's background "
            "(classical GrabCut segmentation) and writes a "
            "transparent-background PNG; optionally asks a Vision "
            "model for a note."
        ),
        tool_affordance=VISION_REMOVE_BACKGROUND_TOOL_AFFORDANCE,
        provider_capability_id=REMOVE_BACKGROUND_PROVIDER_CAPABILITY_ID,
        provider_description=(
            "AI-driven notes on top of a deterministic GrabCut "
            "segmentation, satisfied by a Provider model specialized "
            "for vision understanding. Only consulted when the "
            "caller supplies an instruction; never used to compute "
            "the segmentation mask itself."
        ),
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=CONVERT_FORMAT_CAPABILITY_ID,
        tool_id=CONVERT_FORMAT_TOOL_ID,
        name="Vision - Convert Format",
        tool_description="Deterministically converts a local image to a different file format and writes the result.",
        tool_affordance=VISION_CONVERT_FORMAT_TOOL_AFFORDANCE,
    ),
    _VisionExtendedToolSpec(
        tool_capability_id=COMPRESS_IMAGE_CAPABILITY_ID,
        tool_id=COMPRESS_IMAGE_TOOL_ID,
        name="Vision - Compress Image",
        tool_description="Deterministically re-encodes a local image at a lower quality/size and writes the result.",
        tool_affordance=VISION_COMPRESS_IMAGE_TOOL_AFFORDANCE,
    ),
)
"""
Every deterministic-first `vision.*` TOOL Capability/Tool pair (plus
its optional Provider Capability) this Module additionally registers.
Purely data -- see `_VisionExtendedToolSpec`'s own docstring.
"""
