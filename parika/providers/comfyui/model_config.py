"""
PARIKA ComfyUI Provider - Model/Workflow Configuration

Defines `ComfyUIModelConfig`: the provider's own, entirely internal
mapping from a semantic `GenerationOperation`/`ProviderModel.id` pair
to the concrete ComfyUI model filenames (diffusion model, text
encoder, VAE) needed to build a working workflow.

None of this leaks outward: `GenerationRequest`/`GenerationResult`
(the provider-independent boundary) never mention a checkpoint name, a
CLIP file, or a VAE file. This is exactly the "workflow/model mapping
belongs inside the provider" boundary the architecture requires --
Core and every Module remain unaware that these filenames exist.

Every filename defaults to the model actually discovered on the
developer's ComfyUI instance at the time this provider was built (see
`config/defaults.toml`'s `[providers.comfyui]` section), but every
default is overridable through `Configuration`, and none is
hardcoded as an absolute filesystem path -- only a ComfyUI-relative
model filename (as returned by `GET /models/<folder>`), exactly like
Ollama's `default_model` configuration key.
"""

from __future__ import annotations

from dataclasses import dataclass

# Synthetic ProviderModel ids this provider declares. These are
# provider-local identifiers (never exposed to Core/Modules beyond the
# opaque `ProviderModel.id` string Planner's Model Selection Framework
# already threads through generically), analogous to an Ollama model
# tag such as `"qwen3-coder-next:latest"`.
IMAGE_MODEL_ID = "comfyui/qwen-image"
VIDEO_T2V_MODEL_ID = "comfyui/wan2.1-t2v-1.3b"
VIDEO_VACE_MODEL_ID = "comfyui/wan2.1-vace-1.3b"

# ComfyUI's native `UNETLoader` node only accepts these `weight_dtype`
# choices. `"default"` loads the checkpoint at its own stored
# precision (unchanged behavior); the `fp8_*` choices instruct
# ComfyUI to load/run the checkpoint at that reduced precision
# regardless of how the checkpoint file itself is named -- the
# filename and the loading dtype are independent configuration
# concerns and must never be inferred from each other (a filename
# containing "fp8"/"fp16"/"bf16" is not a reliable signal of the
# dtype a given ComfyUI/model combination actually supports or
# requires).
VIDEO_WEIGHT_DTYPES = frozenset(
    {"default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"}
)

# The diffusion-model *loader/backend* a video model is loaded
# through, independent of both its filename and its `weight_dtype`
# (see `ComfyUIModelConfig`'s docstring for the full independence
# rationale). `"native"` is ComfyUI's own `UNETLoader` node (today's
# only behavior, and the only loader `VIDEO_WEIGHT_DTYPES` applies
# to); `"gguf"` is the `ComfyUI-GGUF` custom node's `UnetLoaderGGUF`
# node (https://github.com/city96/ComfyUI-GGUF), required for
# `.gguf` quantized checkpoints, which `UNETLoader` cannot load. This
# is never inferred from the configured filename (a `.gguf`
# extension is not treated as a loader signal) -- it is always an
# explicit, separate configuration value.
VIDEO_LOADERS = frozenset({"native", "gguf"})

# Default loader for both video models, matching today's (pre-GGUF)
# behavior exactly.
DEFAULT_VIDEO_LOADER = "native"


@dataclass(frozen=True, slots=True, kw_only=True)
class ComfyUIModelConfig:
    """
    Immutable snapshot of the ComfyUI model filenames this provider
    is configured to use.

    Attributes:
        image_diffusion_model:
            Diffusion model filename (relative to ComfyUI's
            `models/diffusion_models/`) used for `image_generate` and
            `image_edit`. A single unified checkpoint is used for
            both operations (see `workflows.py`'s module docstring for
            why `image_edit` is implemented as guided image-to-image
            rather than requiring a dedicated edit-finetuned
            checkpoint).

        image_text_encoder:
            Text encoder filename (relative to
            `models/text_encoders/`) paired with
            `image_diffusion_model`.

        image_vae:
            VAE filename (relative to `models/vae/`) paired with
            `image_diffusion_model`.

        video_t2v_diffusion_model:
            Diffusion model filename used for `video_generate` when
            `VIDEO_T2V_MODEL_ID` is selected -- a text-to-video-only
            checkpoint.

        video_t2v_loader:
            Which ComfyUI node loads `video_t2v_diffusion_model`:
            `"native"` (`UNETLoader`) or `"gguf"` (`UnetLoaderGGUF`,
            required for `.gguf` checkpoints). Independent of both the
            filename and `video_t2v_weight_dtype` -- never inferred
            from the filename's extension (see `VIDEO_LOADERS`).
            Defaults to `"native"`, i.e. today's only behavior.

        video_t2v_weight_dtype:
            `UNETLoader` `weight_dtype` used when loading
            `video_t2v_diffusion_model` with `video_t2v_loader=
            "native"` -- independent of the filename itself (never
            inferred from it; see `VIDEO_WEIGHT_DTYPES`). Defaults to
            `"default"`, i.e. today's behavior of loading the
            checkpoint at its own stored precision. Meaningless (and
            therefore restricted to `"default"`) when
            `video_t2v_loader="gguf"`, since `UnetLoaderGGUF` has no
            equivalent precision-selection input -- a GGUF
            checkpoint's quantization is already baked into the file.

        video_vace_diffusion_model:
            Diffusion model filename used for `video_generate`,
            `video_generate_from_image`, and `video_edit` when
            `VIDEO_VACE_MODEL_ID` is selected -- a versatile
            (VACE-architecture) checkpoint that additionally supports
            image/video conditioning, and is therefore the only
            candidate for the latter two operations.

        video_vace_loader:
            Which ComfyUI node loads `video_vace_diffusion_model`,
            independent of the filename and `video_vace_weight_dtype`
            for the same reason as `video_t2v_loader`. This is what
            lets an operator switch to the installed GGUF VACE
            checkpoint (`video_vace_loader="gguf"`) purely through
            `config/defaults.toml` (or an override layer), with no
            code change.

        video_vace_weight_dtype:
            `UNETLoader` `weight_dtype` used when loading
            `video_vace_diffusion_model` with `video_vace_loader=
            "native"`, independent of the filename for the same
            reason as `video_t2v_weight_dtype`. This is what lets an
            operator switch between, e.g., an FP8-scaled VACE
            checkpoint (`weight_dtype="fp8_e4m3fn"`) and the original
            FP16 VACE checkpoint (`weight_dtype="default"`) purely
            through `config/defaults.toml` (or an override layer),
            with no code change either way. Restricted to `"default"`
            when `video_vace_loader="gguf"`, for the same reason as
            `video_t2v_weight_dtype`.

        video_text_encoder:
            Text encoder filename shared by both Wan checkpoints.

        video_vae:
            VAE filename shared by both Wan checkpoints.
    """

    image_diffusion_model: str = "qwen-image/qwen_image_fp8_e4m3fn.safetensors"
    image_text_encoder: str = "qwen/qwen_2.5_vl_7b_fp8_scaled.safetensors"
    image_vae: str = "qwen-image/qwen_image_vae.safetensors"

    video_t2v_diffusion_model: str = "Wan2.1/wan2.1_t2v_1.3B_bf16.safetensors"
    video_t2v_loader: str = DEFAULT_VIDEO_LOADER
    video_t2v_weight_dtype: str = "default"
    video_vace_diffusion_model: str = "wan2.1_vace_1.3B_fp16.safetensors"
    video_vace_loader: str = DEFAULT_VIDEO_LOADER
    video_vace_weight_dtype: str = "default"
    video_text_encoder: str = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    video_vae: str = "wan_2.1_vae.safetensors"

    def __post_init__(self) -> None:
        """
        Validate that the configured video `loader`/`weight_dtype`
        values are among the choices this provider actually
        implements (see `VIDEO_LOADERS`/`VIDEO_WEIGHT_DTYPES`), and
        that `weight_dtype` is not set to a native-only value for a
        model configured with `video_*_loader="gguf"` (`UnetLoaderGGUF`
        has no `weight_dtype` input to apply it to).
        """

        self._validate_video_model(
            loader=self.video_t2v_loader,
            weight_dtype=self.video_t2v_weight_dtype,
            loader_field="video_t2v_loader",
            weight_dtype_field="video_t2v_weight_dtype",
        )
        self._validate_video_model(
            loader=self.video_vace_loader,
            weight_dtype=self.video_vace_weight_dtype,
            loader_field="video_vace_loader",
            weight_dtype_field="video_vace_weight_dtype",
        )

    def _validate_video_model(
        self,
        *,
        loader: str,
        weight_dtype: str,
        loader_field: str,
        weight_dtype_field: str,
    ) -> None:
        if loader not in VIDEO_LOADERS:
            raise ValueError(
                f"{loader_field} must be one of {sorted(VIDEO_LOADERS)}, "
                f"got {loader!r}."
            )

        if weight_dtype not in VIDEO_WEIGHT_DTYPES:
            raise ValueError(
                f"{weight_dtype_field} must be one of "
                f"{sorted(VIDEO_WEIGHT_DTYPES)}, got {weight_dtype!r}."
            )

        if loader == "gguf" and weight_dtype != "default":
            raise ValueError(
                f"{weight_dtype_field}={weight_dtype!r} is not valid "
                f"alongside {loader_field}='gguf': ComfyUI's "
                "UnetLoaderGGUF node has no weight_dtype input (a "
                "GGUF checkpoint's quantization is already fixed by "
                f"the file itself), so {weight_dtype_field} must be "
                "left at its default ('default') when the loader is "
                "'gguf'."
            )

    def diffusion_model_for(self, model_id: str) -> str | None:
        """
        Resolve a synthetic `ProviderModel.id` to its concrete
        ComfyUI diffusion model filename, or `None` if `model_id` is
        not one this provider declares.
        """

        return {
            IMAGE_MODEL_ID: self.image_diffusion_model,
            VIDEO_T2V_MODEL_ID: self.video_t2v_diffusion_model,
            VIDEO_VACE_MODEL_ID: self.video_vace_diffusion_model,
        }.get(model_id)

    def weight_dtype_for(self, model_id: str) -> str | None:
        """
        Resolve a synthetic `ProviderModel.id` to the `UNETLoader`
        `weight_dtype` that must be used alongside
        `diffusion_model_for(model_id)`, or `None` if `model_id` is
        not one of the video models this provider declares.
        """

        return {
            VIDEO_T2V_MODEL_ID: self.video_t2v_weight_dtype,
            VIDEO_VACE_MODEL_ID: self.video_vace_weight_dtype,
        }.get(model_id)

    def loader_for(self, model_id: str) -> str | None:
        """
        Resolve a synthetic `ProviderModel.id` to the loader/backend
        (`VIDEO_LOADERS`) that must be used to load
        `diffusion_model_for(model_id)`, or `None` if `model_id` is
        not one of the video models this provider declares.
        """

        return {
            VIDEO_T2V_MODEL_ID: self.video_t2v_loader,
            VIDEO_VACE_MODEL_ID: self.video_vace_loader,
        }.get(model_id)
