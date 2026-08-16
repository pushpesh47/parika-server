"""
PARIKA Generation Module - Manifest

Defines the static ModuleManifest describing the Generation Module.

Registers `image.generate`, `image.edit`, `video.generate`,
`video.generate_from_image`, and `video.edit`: Tool-backed
orchestrators that obtain any input image/video through the existing
Filesystem Capability and delegate the actual generation to their own
internal, Provider-backed Capabilities -- satisfied today by the
ComfyUI Provider (`parika.providers.comfyui`), but never hard-coded to
it; any future compatible generation Provider (declaring
`ModelCapability.IMAGE_GENERATION`/`VIDEO_GENERATION`) is automatically
eligible through the unmodified Model Selection Framework.

This is a separate Module from Vision (image *understanding*) and
Video (video *understanding*) by design -- see the top-level
architecture task's own "generation vs understanding" distinction.
Vision and Video's own `vision.remove_background`/
`vision.enhance_image` Capabilities are deliberately left unmodified
by this Module (see their own Provider-selection investigation
recorded in the project's final report); nothing here replaces or
depends on either existing Module.

`video.generate`/`video.generate_from_image`/`video.edit` intentionally
keep the `video.` capability id prefix despite living in a different
Python package than `parika.modules.video` -- capability id
namespacing is a semantic-domain concern, not a module-location
concern (the existing Video Module already demonstrates this by
registering its own Provider Capabilities under
`CapabilityCategory.VISION`, a different category than its own
domain, without any naming inconsistency).
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .module_driver import GenerationModuleDriver

GENERATION_MODULE_ID = "generation"
GENERATION_MODULE_VERSION = "1.0.0"


def create_generation_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Generation Module.
    """

    return ModuleManifest(
        id=GENERATION_MODULE_ID,
        name="Generation",
        version=GENERATION_MODULE_VERSION,
        description=(
            "Registers the generative media family: `image.generate`, "
            "`image.edit`, `video.generate`, "
            "`video.generate_from_image`, and `video.edit` "
            "(Tool-backed orchestrators that obtain any input image/"
            "video through the existing Filesystem Capability and "
            "generate through a Provider-backed generation model), "
            "together with their internal, IMAGE_GENERATION/"
            "VIDEO_GENERATION-category Provider Capabilities, each "
            "satisfied by a compatible Provider model (e.g. ComfyUI's "
            "Qwen-Image/Wan2.1 models), never advertised directly to "
            "the general chat model."
        ),
        author="PARIKA",
        license="MIT",
        tags=("generation", "image", "video"),
        driver="parika.modules.generation.module_driver.GenerationModuleDriver",
    )


def create_generation_module(driver: GenerationModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Generation Module.
    """

    return Module(
        id=GENERATION_MODULE_ID,
        manifest=create_generation_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
