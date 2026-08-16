"""
PARIKA Media Module - Manifest

Defines the static ModuleManifest describing the Media Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .module_driver import MediaModuleDriver

MEDIA_MODULE_ID = "media"
MEDIA_MODULE_VERSION = "1.0.0"


def create_media_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Media Module.
    """

    return ModuleManifest(
        id=MEDIA_MODULE_ID,
        name="Media",
        version=MEDIA_MODULE_VERSION,
        description=(
            "Provides the media.play, media.pause, media.resume, "
            "media.stop, media.skip, media.previous, media.seek, "
            "media.set_volume, media.mute, media.unmute, media.show, "
            "media.hide, and media.get_state Capabilities: "
            "provider-independent media intent, resolution, and "
            "control/state synchronization with a separate Web "
            "Client, which performs actual playback. PARIKA never "
            "decodes, streams, or plays audio/video itself - see "
            "docs/architecture/adr/0004-media-capability.md."
        ),
        author="PARIKA",
        license="MIT",
        tags=("media", "music", "video", "playback"),
        driver="parika.modules.media.module_driver.MediaModuleDriver",
    )


def create_media_module(driver: MediaModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Media Module.
    """

    return Module(
        id=MEDIA_MODULE_ID,
        manifest=create_media_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
