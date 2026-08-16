"""
PARIKA OCR Module - Manifest

Defines the static ModuleManifest describing the OCR Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .module_driver import OcrModuleDriver

OCR_MODULE_ID = "ocr"
OCR_MODULE_VERSION = "1.0.0"


def create_ocr_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the OCR Module.
    """

    return ModuleManifest(
        id=OCR_MODULE_ID,
        name="OCR",
        version=OCR_MODULE_VERSION,
        description=(
            "Registers `ocr.extract_text` (a Tool-backed orchestrator "
            "that obtains an image or PDF through the existing "
            "Filesystem Capability, deterministically preprocesses/"
            "analyzes it, and recognizes its text through a "
            "Provider-backed OCR model) and `ocr.provider_extract_text` "
            "(its OCR-category capability, satisfied by a Provider "
            "model such as `glm-ocr`, never advertised directly to the "
            "general chat model), plus six further Tool "
            "Capabilities built on the same two Capabilities: "
            "`ocr.detect_orientation`/`ocr.detect_quality` "
            "(deterministic-only), `ocr.detect_language`/"
            "`ocr.extract_layout` (composable over already-recognized "
            "text), and `ocr.extract_table`/`ocr.extract_form` "
            "(structured extraction). Mirrors the Coding Agent "
            "Module's `coding.execute_task`/`coding.plan_change` shape "
            "exactly. `document.extract_text` (formerly implemented "
            "here temporarily) has moved to the first-class Document "
            "Module (`parika/modules/document/`), which reuses "
            "`ocr.extract_text` internally for scanned/image-only "
            "PDFs."
        ),
        author="PARIKA",
        license="MIT",
        tags=("ocr", "vision", "image", "document", "pdf"),
        driver="parika.modules.ocr.module_driver.OcrModuleDriver",
    )


def create_ocr_module(driver: OcrModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the OCR Module.

    Args:
        driver:
            Constructed OcrModuleDriver instance for this module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=OCR_MODULE_ID,
        manifest=create_ocr_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
