"""
PARIKA ComfyUI Provider - Model Discovery

Determines which of this provider's declared synthetic
`ProviderModel`s are actually usable right now, by checking the live
ComfyUI server's own model listing endpoints -- exactly the
"installed environment is authoritative" rule this provider follows
throughout. A model whose configured diffusion-model filename is not
present in the listing for its configured loader is not returned at
all, so Model Selection never proposes a model ComfyUI cannot
actually run.

Native (`UNETLoader`) models are listed by `GET
/models/diffusion_models`; GGUF (`UnetLoaderGGUF`) models are listed
separately, by `GET /models/unet_gguf` -- ComfyUI-GGUF registers `.gguf`
checkpoints under that distinct folder name rather than
`diffusion_models` (verified against a live ComfyUI 0.31.1 +
ComfyUI-GGUF installation). Which listing a given video model's
installed-ness is checked against is decided purely by that model's
configured loader (`ComfyUIModelConfig.video_t2v_loader`/
`video_vace_loader`) -- never by the filename's extension.

Mirrors `parika.providers.ollama.discovery.build_provider_model()`'s
role for this provider: pure data transformation, no orchestration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider_model import ProviderModel

from .model_config import (
    IMAGE_MODEL_ID,
    VIDEO_T2V_MODEL_ID,
    VIDEO_VACE_MODEL_ID,
    ComfyUIModelConfig,
)

_DIFFUSION_MODELS_PATH = "/models/diffusion_models"
_UNET_GGUF_MODELS_PATH = "/models/unet_gguf"

# Which ComfyUI `/models/<folder>` listing is authoritative for a
# given `ComfyUIModelConfig.video_t2v_loader`/`video_vace_loader`
# value. Kept alongside the paths above, not derived from a
# checkpoint filename.
_LOADER_MODEL_LISTING_PATHS = {
    "native": _DIFFUSION_MODELS_PATH,
    "gguf": _UNET_GGUF_MODELS_PATH,
}


def model_listing_path_for_loader(loader: str) -> str:
    """
    Resolve the ComfyUI `GET /models/<folder>` path that lists
    installed checkpoints for `loader` (a `ComfyUIModelConfig.
    video_t2v_loader`/`video_vace_loader` value).

    Used by `driver.py` to decide which additional listing (beyond
    the always-queried `_DIFFUSION_MODELS_PATH`, needed for the image
    model and any native video model) it must fetch before calling
    `discover_models()`.
    """

    return _LOADER_MODEL_LISTING_PATHS[loader]


def discover_models(
    *,
    installed_diffusion_models: Mapping[str, Any] | list[Any],
    installed_gguf_models: Mapping[str, Any] | list[Any] = (),
    model_config: ComfyUIModelConfig,
) -> tuple[ProviderModel, ...]:
    """
    Build the set of usable `ProviderModel`s given ComfyUI's own
    reported lists of installed model files.

    Returns a plain tuple, not a `frozenset`, exactly like
    `parika.providers.ollama.driver.OllamaProviderDriver.list_models()`:
    `ProviderModel` carries a `metadata: Mapping[str, object]` field
    (a `MappingProxyType`), which -- like the underlying `dict` it
    wraps -- is not hashable, so no `ProviderModel` with any metadata
    can ever actually be placed in a `frozenset`. `ProviderDriver
    .discover_models()`'s declared `frozenset[ProviderModel]` return
    type is a pre-existing, provider-independent core annotation this
    provider does not control; `driver.py`'s own `discover_models()`
    returns this tuple through that signature with the same
    `# type: ignore[return-value]` Ollama's driver already uses.

    Args:
        installed_diffusion_models:
            The parsed JSON body of `GET /models/diffusion_models`
            (a bare list of filename strings). Authoritative for the
            image model and any video model configured with
            `video_*_loader="native"`.

        installed_gguf_models:
            The parsed JSON body of `GET /models/unet_gguf` (a bare
            list of filename strings), or `()` if it was not fetched
            (e.g. because no video model is configured with
            `video_*_loader="gguf"`). Authoritative for any video
            model configured with `video_*_loader="gguf"`.

        model_config:
            This provider's configured filename/loader mapping.

    Returns:
        One `ProviderModel` per declared synthetic model whose
        configured diffusion-model filename is present in the
        listing corresponding to its configured loader. Empty if none
        are installed.
    """

    installed = frozenset(
        str(entry) for entry in installed_diffusion_models
        if isinstance(entry, str)
    )
    installed_gguf = frozenset(
        str(entry) for entry in installed_gguf_models if isinstance(entry, str)
    )

    def _is_installed(*, diffusion_model: str, loader: str) -> bool:
        listing = installed_gguf if loader == "gguf" else installed

        return diffusion_model in listing

    models: list[ProviderModel] = []

    if model_config.image_diffusion_model in installed:
        models.append(
            ProviderModel(
                id=IMAGE_MODEL_ID,
                name="Qwen-Image (ComfyUI)",
                description=(
                    "Local Qwen-Image text-to-image diffusion model, "
                    "also used (via guided image-to-image) for "
                    "image editing."
                ),
                capabilities=frozenset({ModelCapability.IMAGE_GENERATION}),
                execution_features=frozenset(),
                specializations=frozenset(
                    {"image_generation", "image_editing"}
                ),
                supported_modalities=frozenset({"image"}),
            )
        )

    if _is_installed(
        diffusion_model=model_config.video_t2v_diffusion_model,
        loader=model_config.video_t2v_loader,
    ):
        models.append(
            ProviderModel(
                id=VIDEO_T2V_MODEL_ID,
                name="Wan2.1 T2V 1.3B (ComfyUI)",
                description=(
                    "Local Wan2.1 text-to-video-only diffusion model. "
                    "Does not support image/video conditioning."
                ),
                capabilities=frozenset({ModelCapability.VIDEO_GENERATION}),
                execution_features=frozenset(),
                specializations=frozenset({"video_generation"}),
                supported_modalities=frozenset({"video"}),
            )
        )

    if _is_installed(
        diffusion_model=model_config.video_vace_diffusion_model,
        loader=model_config.video_vace_loader,
    ):
        models.append(
            ProviderModel(
                id=VIDEO_VACE_MODEL_ID,
                name="Wan2.1 VACE 1.3B (ComfyUI)",
                description=(
                    "Local Wan2.1 VACE (versatile creation/editing) "
                    "diffusion model: text-to-video, image-to-video "
                    "(reference image), and video-to-video editing "
                    "(control video)."
                ),
                capabilities=frozenset({ModelCapability.VIDEO_GENERATION}),
                execution_features=frozenset(),
                specializations=frozenset(
                    {
                        "video_generation",
                        "video_generation_from_image",
                        "video_editing",
                    }
                ),
                supported_modalities=frozenset({"video"}),
            )
        )

    return tuple(models)
