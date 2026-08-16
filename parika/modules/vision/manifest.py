"""
PARIKA Vision Module - Manifest

Defines the static ModuleManifest describing the Vision Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .module_driver import VisionModuleDriver

VISION_MODULE_ID = "vision"
VISION_MODULE_VERSION = "1.0.0"


def create_vision_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Vision Module.
    """

    return ModuleManifest(
        id=VISION_MODULE_ID,
        name="Vision",
        version=VISION_MODULE_VERSION,
        description=(
            "Registers the general-purpose image understanding "
            "family: `vision.describe_image`, `vision.answer_question`, "
            "`vision.detect_objects`, `vision.analyze_scene`, "
            "`vision.analyze_ui`, `vision.analyze_chart`, "
            "`vision.analyze_diagram`, `vision.detect_logos`, and "
            "`vision.reason_about_image` (Tool-backed orchestrators "
            "that obtain an image through the existing Filesystem "
            "Capability and analyze it through a Provider-backed "
            "Vision model), together with their internal, "
            "VISION-category Provider Capabilities, each satisfied by "
            "a Provider model such as `minicpm-v4.5`, never advertised "
            "directly to the general chat model. Also registers "
            "twenty-two deterministic-first Capabilities -- image "
            "comparison/difference detection, object counting/"
            "classification, face/QR/barcode detection, quality/blur/"
            "rotation/anomaly analysis, multi-image search/similarity/"
            "duplicate detection, and image editing (crop/resize/"
            "rotate/flip/enhance/background removal/format conversion/"
            "compression) -- each preferring a classical computer "
            "vision algorithm over a Provider model call, escalating "
            "to its own Provider Capability only when semantic "
            "reasoning is genuinely required (see `module_driver.py`'s "
            "`_VISION_EXTENDED_TOOL_SPECS`). Mirrors the OCR Module's "
            "`ocr.extract_text`/`ocr.provider_extract_text` shape "
            "exactly, repeated once per Vision Capability."
        ),
        author="PARIKA",
        license="MIT",
        tags=("vision", "image"),
        driver="parika.modules.vision.module_driver.VisionModuleDriver",
    )


def create_vision_module(driver: VisionModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Vision Module.

    Args:
        driver:
            Constructed VisionModuleDriver instance for this module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=VISION_MODULE_ID,
        manifest=create_vision_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
