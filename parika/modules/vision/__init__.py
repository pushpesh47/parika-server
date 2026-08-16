"""
PARIKA Vision Module package.

Integrates the general-purpose Vision Capability family
(`vision.describe_image`, `vision.answer_question`,
`vision.detect_objects`, `vision.analyze_scene`, `vision.analyze_ui`,
`vision.analyze_chart`, `vision.analyze_diagram`, and their internal
Provider-backed counterparts `vision.provider_describe_image`,
`vision.provider_answer_question`, `vision.provider_detect_objects`,
`vision.provider_analyze_scene`, `vision.provider_analyze_ui`,
`vision.provider_analyze_chart`, `vision.provider_analyze_diagram`)
into PARIKA through ModuleManager, CapabilityRegistry, and
ToolManager, following exactly the same two-Capability-per-Tool (Tool
orchestrator + Provider-backed) shape the OCR Module already
established.
"""

from __future__ import annotations

from .exceptions import VisionAnalysisError, VisionError, VisionImageReadError
from .driver import VisionToolDriver
from .manifest import (
    VISION_MODULE_ID,
    VISION_MODULE_VERSION,
    create_vision_module,
    create_vision_module_manifest,
)
from .module_driver import (
    MODULE_HEALTH_COMPONENT_ID,
    VisionModuleDriver,
    VisionToolSpec,
)

__all__ = [
    "MODULE_HEALTH_COMPONENT_ID",
    "VISION_MODULE_ID",
    "VISION_MODULE_VERSION",
    "VisionAnalysisError",
    "VisionError",
    "VisionImageReadError",
    "VisionModuleDriver",
    "VisionToolDriver",
    "VisionToolSpec",
    "create_vision_module",
    "create_vision_module_manifest",
]
