"""
PARIKA OCR Module package.

Integrates OCR into PARIKA through ModuleManager, CapabilityRegistry,
and ToolManager, following exactly the same two-Capability (Tool
orchestrator + Provider-backed) shape the Coding Agent Module already
established. Eight Capabilities in total:

- `ocr.extract_text` / `ocr.provider_extract_text` -- the original pair.
- `ocr.detect_orientation` / `ocr.detect_quality` -- deterministic-
  only (`analysis_driver.py`), never a model call.
- `ocr.detect_language` / `ocr.extract_layout` -- composable
  (`text_tools_driver.py`): accept already-recognized text at zero
  additional cost, or fall back to a fresh recognition call.
- `ocr.extract_table` / `ocr.extract_form` -- structured extraction
  (`structured_driver.py`), both reusing `ocr.provider_extract_text`
  internally rather than registering a new Provider Capability each.

`document.extract_text` (formerly a temporary implementation detail
of this Module) has moved to the first-class Document Module
(`parika/modules/document/`), which reuses `ocr.extract_text`
internally for scanned/image-only PDFs.

`preprocessing.py`, `pdf_support.py`, and `language.py` provide the
deterministic image/PDF/language algorithms this Module's Tools call;
`config.py` detects the optional `ocr` dependency group
(`pyproject.toml`) at runtime, gracefully degrading -- never crashing
-- when it is not installed, following exactly the same pattern
`parika/tools/coding/config.py` established for its own `coding`
extra.
"""

from __future__ import annotations

from .analysis_driver import OcrOrientationToolDriver, OcrQualityToolDriver
from .config import OcrToolConfig, load_ocr_config
from .driver import OcrToolDriver
from .exceptions import (
    OcrDependencyUnavailableError,
    OcrError,
    OcrImageReadError,
    OcrPdfError,
    OcrRecognitionError,
)
from .manifest import (
    OCR_MODULE_ID,
    OCR_MODULE_VERSION,
    create_ocr_module,
    create_ocr_module_manifest,
)
from .module_driver import (
    DETECT_LANGUAGE_CAPABILITY_ID,
    DETECT_ORIENTATION_CAPABILITY_ID,
    DETECT_QUALITY_CAPABILITY_ID,
    EXTRACT_FORM_CAPABILITY_ID,
    EXTRACT_LAYOUT_CAPABILITY_ID,
    EXTRACT_TABLE_CAPABILITY_ID,
    EXTRACT_TEXT_CAPABILITY_ID,
    MODULE_HEALTH_COMPONENT_ID,
    PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
    OcrModuleDriver,
)
from .structured_driver import OcrFormToolDriver, OcrTableToolDriver
from .text_tools_driver import OcrLanguageToolDriver, OcrLayoutToolDriver

__all__ = [
    "DETECT_LANGUAGE_CAPABILITY_ID",
    "DETECT_ORIENTATION_CAPABILITY_ID",
    "DETECT_QUALITY_CAPABILITY_ID",
    "EXTRACT_FORM_CAPABILITY_ID",
    "EXTRACT_LAYOUT_CAPABILITY_ID",
    "EXTRACT_TABLE_CAPABILITY_ID",
    "EXTRACT_TEXT_CAPABILITY_ID",
    "MODULE_HEALTH_COMPONENT_ID",
    "OCR_MODULE_ID",
    "OCR_MODULE_VERSION",
    "PROVIDER_EXTRACT_TEXT_CAPABILITY_ID",
    "OcrDependencyUnavailableError",
    "OcrError",
    "OcrFormToolDriver",
    "OcrImageReadError",
    "OcrLanguageToolDriver",
    "OcrLayoutToolDriver",
    "OcrModuleDriver",
    "OcrOrientationToolDriver",
    "OcrPdfError",
    "OcrQualityToolDriver",
    "OcrRecognitionError",
    "OcrTableToolDriver",
    "OcrToolConfig",
    "OcrToolDriver",
    "create_ocr_module",
    "create_ocr_module_manifest",
    "load_ocr_config",
]
