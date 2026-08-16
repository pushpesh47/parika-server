"""
PARIKA ComfyUI Provider - Workflow Construction

Builds the concrete ComfyUI API-format workflow graphs (plain
`dict[str, {"class_type": ..., "inputs": ...}]` payloads for
`POST /prompt`) for each supported `GenerationOperation`. This is the
one place ComfyUI node types, node ids, checkpoints, samplers, and
latent-graph wiring exist anywhere in PARIKA -- Core and every Module
never see any of it (see `GenerationRequest`/`GenerationResult`).

Every graph shape here was interactively verified against a live,
locally installed ComfyUI 0.31.1 instance with the models actually
present on that instance (Qwen-Image for images; Wan2.1 T2V-1.3B and
Wan2.1-VACE-1.3B for video) before being encoded here -- none of this
is guessed from documentation alone.

Image generation and image editing
-----------------------------------
Only one diffusion checkpoint is installed for images: the *base*
Qwen-Image text-to-image model (`qwen_image_fp8_e4m3fn.safetensors`).
The dedicated instruction-following edit checkpoint
(`qwen_image_edit_fp8_e4m3fn.safetensors`) is **not** installed.
Verified empirically: running the official Qwen-Image-Edit node
(`TextEncodeQwenImageEdit`) against the base checkpoint executes
without error but does not reliably follow the edit instruction (the
base model was never trained for that conditioning). Ordinary guided
image-to-image -- encode the source image to a latent
(`VAEEncode`), then run `KSampler` at a partial `denoise` value
against a new text prompt -- was empirically confirmed to both run
correctly *and* meaningfully respect the requested change while
preserving the source image's composition, and requires nothing
beyond the base checkpoint every text-to-image model has. `image_edit`
is therefore implemented as guided image-to-image, not
instruction-conditioned editing; see this provider's own docstring and
the project's final report for the resulting fidelity trade-off (works
well for global/style changes; less precise for spatially localized
instructions than a dedicated edit model would be).

Video generation and video editing
-----------------------------------
Two Wan2.1 diffusion checkpoints are installed: a text-to-video-only
1.3B model, and a 1.3B "VACE" (versatile creation/editing) model.
`WanVaceToVideo` accepts an optional `reference_image` (image-to-video)
and an optional `control_video` (video-to-video/editing), so only the
VACE checkpoint is used for `video_generate_from_image` and
`video_edit`; either checkpoint can serve plain `video_generate`.

Each video checkpoint is loaded through whichever ComfyUI node its
configured `loader` (`ComfyUIModelConfig.video_t2v_loader`/
`video_vace_loader`) selects: ComfyUI's native `UNETLoader` for
`"native"` (today's only behavior), or the `ComfyUI-GGUF` custom
node's `UnetLoaderGGUF` for `"gguf"` (needed for `.gguf`-quantized
checkpoints, which `UNETLoader` cannot load). See
`_diffusion_model_loader_node()`; this is the only place either
loader's ComfyUI node type is named, and the choice is always driven
by the explicit `loader` value -- never by the diffusion model
filename's extension.
"""

from __future__ import annotations

from typing import Any

from .model_config import ComfyUIModelConfig

WorkflowGraph = dict[str, dict[str, Any]]

# Internal, fixed node ids. These never leave this module.
_IMAGE_OUTPUT_NODE_ID = "save"
_VIDEO_OUTPUT_NODE_ID = "save"

# ComfyUI node type used to load a video diffusion model for each
# `ComfyUIModelConfig` loader/backend value (`model_config.
# VIDEO_LOADERS`). The only place either loader's ComfyUI node type
# is named -- see `_diffusion_model_loader_node()`.
_LOADER_NODE_TYPES = {
    "native": "UNETLoader",
    "gguf": "UnetLoaderGGUF",
}

# Image generation/editing sampling defaults. Not part of
# `GenerationRequest` -- these are ComfyUI/model-specific
# implementation details the provider owns entirely (see this
# module's docstring and `GenerationRequest`'s own docstring).
_IMAGE_STEPS = 20
_IMAGE_CFG = 2.5
_IMAGE_SAMPLER = "euler"
_IMAGE_SCHEDULER = "simple"
_IMAGE_SHIFT = 3.1
_IMAGE_EDIT_DENOISE = 0.65

# Video generation/editing sampling defaults, matching the installed
# Wan2.1/VACE models' own documented "default" (non-LoRA-accelerated)
# settings.
_VIDEO_STEPS = 20
_VIDEO_CFG = 6.0
_VIDEO_SAMPLER = "uni_pc"
_VIDEO_SCHEDULER = "simple"
_VIDEO_SHIFT = 8.0


def build_image_generate_workflow(
    *,
    model_config: ComfyUIModelConfig,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
) -> tuple[WorkflowGraph, str]:
    """
    Build the text-to-image workflow (Qwen-Image).

    Returns:
        `(graph, output_node_id)`. `output_node_id` is the
        `SaveImage` node whose output the caller should look for in
        `/history`.
    """

    graph: WorkflowGraph = {
        "clip": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": model_config.image_text_encoder,
                "type": "qwen_image",
            },
        },
        "unet": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": model_config.image_diffusion_model,
                "weight_dtype": "default",
            },
        },
        "vae": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": model_config.image_vae},
        },
        "positive": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["clip", 0]},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["clip", 0]},
        },
        "latent": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "model_sampling": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"shift": _IMAGE_SHIFT, "model": ["unet", 0]},
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": _IMAGE_STEPS,
                "cfg": _IMAGE_CFG,
                "sampler_name": _IMAGE_SAMPLER,
                "scheduler": _IMAGE_SCHEDULER,
                "denoise": 1.0,
                "model": ["model_sampling", 0],
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "latent_image": ["latent", 0],
            },
        },
        "decode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]},
        },
        _IMAGE_OUTPUT_NODE_ID: {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["decode", 0],
                "filename_prefix": "parika/image_generate",
            },
        },
    }

    return graph, _IMAGE_OUTPUT_NODE_ID


def build_image_edit_workflow(
    *,
    model_config: ComfyUIModelConfig,
    prompt: str,
    negative_prompt: str,
    seed: int,
    input_image_name: str,
) -> tuple[WorkflowGraph, str]:
    """
    Build the guided image-to-image editing workflow (Qwen-Image base
    checkpoint, partial-denoise `KSampler` against the source image's
    own encoded latent). See this module's docstring for why this
    shape was chosen over instruction-conditioned editing.

    Returns:
        `(graph, output_node_id)`.
    """

    graph: WorkflowGraph = {
        "clip": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": model_config.image_text_encoder,
                "type": "qwen_image",
            },
        },
        "unet": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": model_config.image_diffusion_model,
                "weight_dtype": "default",
            },
        },
        "vae": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": model_config.image_vae},
        },
        "load_image": {
            "class_type": "LoadImage",
            "inputs": {"image": input_image_name},
        },
        "encode_source": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["load_image", 0], "vae": ["vae", 0]},
        },
        "positive": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["clip", 0]},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["clip", 0]},
        },
        "model_sampling": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"shift": _IMAGE_SHIFT, "model": ["unet", 0]},
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": _IMAGE_STEPS,
                "cfg": _IMAGE_CFG,
                "sampler_name": _IMAGE_SAMPLER,
                "scheduler": _IMAGE_SCHEDULER,
                "denoise": _IMAGE_EDIT_DENOISE,
                "model": ["model_sampling", 0],
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "latent_image": ["encode_source", 0],
            },
        },
        "decode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]},
        },
        _IMAGE_OUTPUT_NODE_ID: {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["decode", 0],
                "filename_prefix": "parika/image_edit",
            },
        },
    }

    return graph, _IMAGE_OUTPUT_NODE_ID


def _diffusion_model_loader_node(
    *,
    loader: str,
    diffusion_model: str,
    weight_dtype: str,
) -> dict[str, Any]:
    """
    Build the "unet" node that loads `diffusion_model`, using
    whichever ComfyUI node `loader` (a `ComfyUIModelConfig.
    video_t2v_loader`/`video_vace_loader` value) selects -- the only
    place either loader's ComfyUI node type is named. Model filename,
    loader, and `weight_dtype` are independent configuration concerns
    (see `ComfyUIModelConfig`'s docstring); none is inferred from the
    others here.

    `weight_dtype` is only meaningful for `loader="native"`
    (`UNETLoader`'s own input); `ComfyUIModelConfig` already
    validates it is left at `"default"` whenever `loader="gguf"`, so
    it is simply omitted from `UnetLoaderGGUF`'s inputs, which has no
    equivalent input to receive it.
    """

    class_type = _LOADER_NODE_TYPES.get(loader)

    if class_type is None:
        # ComfyUIModelConfig already validates `loader` against
        # VIDEO_LOADERS at construction time -- reaching this means
        # an internal inconsistency, not a user configuration error.
        raise ValueError(
            f"Unsupported ComfyUI diffusion model loader {loader!r}; "
            f"expected one of {sorted(_LOADER_NODE_TYPES)}."
        )

    if loader == "native":
        return {
            "class_type": class_type,
            "inputs": {"unet_name": diffusion_model, "weight_dtype": weight_dtype},
        }

    return {"class_type": class_type, "inputs": {"unet_name": diffusion_model}}


def _video_base_graph(
    *,
    model_config: ComfyUIModelConfig,
    diffusion_model: str,
    weight_dtype: str,
    loader: str,
    prompt: str,
    negative_prompt: str,
) -> WorkflowGraph:
    """
    Shared model/CLIP/VAE/text-encode nodes for every Wan/VACE video
    workflow. `weight_dtype` is the loading precision to use for
    `diffusion_model` when `loader="native"`, and `loader` selects
    which ComfyUI node loads it (see `_diffusion_model_loader_node()`)
    -- both configured independently of the filename itself (see
    `ComfyUIModelConfig`'s docstring).
    """

    return {
        "clip": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": model_config.video_text_encoder,
                "type": "wan",
            },
        },
        "unet": _diffusion_model_loader_node(
            loader=loader, diffusion_model=diffusion_model, weight_dtype=weight_dtype
        ),
        "vae": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": model_config.video_vae},
        },
        "positive": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["clip", 0]},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["clip", 0]},
        },
        "model_sampling": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"shift": _VIDEO_SHIFT, "model": ["unet", 0]},
        },
    }


def _video_tail(
    *,
    vace_node_id: str,
    fps: float,
    filename_prefix: str,
) -> WorkflowGraph:
    """
    Shared sampler/decode/encode tail wired to a `WanVaceToVideo` node
    with id `vace_node_id`, common to every video workflow below.
    """

    return {
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0,
                "steps": _VIDEO_STEPS,
                "cfg": _VIDEO_CFG,
                "sampler_name": _VIDEO_SAMPLER,
                "scheduler": _VIDEO_SCHEDULER,
                "denoise": 1.0,
                "model": ["model_sampling", 0],
                "positive": [vace_node_id, 0],
                "negative": [vace_node_id, 1],
                "latent_image": [vace_node_id, 2],
            },
        },
        "trim": {
            "class_type": "TrimVideoLatent",
            "inputs": {
                "samples": ["sampler", 0],
                "trim_amount": [vace_node_id, 3],
            },
        },
        "decode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["trim", 0], "vae": ["vae", 0]},
        },
        "assemble": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["decode", 0], "fps": fps},
        },
        _VIDEO_OUTPUT_NODE_ID: {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["assemble", 0],
                "filename_prefix": filename_prefix,
                "format": "auto",
                "codec": "auto",
            },
        },
    }


def build_video_generate_workflow(
    *,
    model_config: ComfyUIModelConfig,
    diffusion_model: str,
    weight_dtype: str,
    loader: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    length: int,
    fps: float,
    seed: int,
) -> tuple[WorkflowGraph, str]:
    """
    Build the text-to-video workflow. Works with either installed Wan
    checkpoint (`diffusion_model`/`weight_dtype`/`loader`): the
    versatile VACE model handles pure text-to-video by simply
    omitting `reference_image`/`control_video`.

    Returns:
        `(graph, output_node_id)`.
    """

    graph = _video_base_graph(
        model_config=model_config,
        diffusion_model=diffusion_model,
        weight_dtype=weight_dtype,
        loader=loader,
        prompt=prompt,
        negative_prompt=negative_prompt,
    )
    graph["vace"] = {
        "class_type": "WanVaceToVideo",
        "inputs": {
            "positive": ["positive", 0],
            "negative": ["negative", 0],
            "vae": ["vae", 0],
            "width": width,
            "height": height,
            "length": length,
            "batch_size": 1,
            "strength": 1.0,
        },
    }
    graph.update(
        _video_tail(
            vace_node_id="vace",
            fps=fps,
            filename_prefix="parika/video_generate",
        )
    )
    graph["sampler"]["inputs"]["seed"] = seed

    return graph, _VIDEO_OUTPUT_NODE_ID


def build_video_generate_from_image_workflow(
    *,
    model_config: ComfyUIModelConfig,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    length: int,
    fps: float,
    seed: int,
    reference_image_name: str,
) -> tuple[WorkflowGraph, str]:
    """
    Build the image-to-video workflow (VACE checkpoint only --
    `reference_image` conditioning).

    Returns:
        `(graph, output_node_id)`.
    """

    graph = _video_base_graph(
        model_config=model_config,
        diffusion_model=model_config.video_vace_diffusion_model,
        weight_dtype=model_config.video_vace_weight_dtype,
        loader=model_config.video_vace_loader,
        prompt=prompt,
        negative_prompt=negative_prompt,
    )
    graph["load_reference_image"] = {
        "class_type": "LoadImage",
        "inputs": {"image": reference_image_name},
    }
    graph["vace"] = {
        "class_type": "WanVaceToVideo",
        "inputs": {
            "positive": ["positive", 0],
            "negative": ["negative", 0],
            "vae": ["vae", 0],
            "width": width,
            "height": height,
            "length": length,
            "batch_size": 1,
            "strength": 1.0,
            "reference_image": ["load_reference_image", 0],
        },
    }
    graph.update(
        _video_tail(
            vace_node_id="vace",
            fps=fps,
            filename_prefix="parika/video_generate_from_image",
        )
    )
    graph["sampler"]["inputs"]["seed"] = seed

    return graph, _VIDEO_OUTPUT_NODE_ID


def build_video_edit_workflow(
    *,
    model_config: ComfyUIModelConfig,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    length: int,
    fps: float,
    seed: int,
    control_video_name: str,
) -> tuple[WorkflowGraph, str]:
    """
    Build the video-to-video editing workflow (VACE checkpoint only --
    `control_video` conditioning, decoded from the uploaded source
    video via `LoadVideo` + `GetVideoComponents`).

    Returns:
        `(graph, output_node_id)`.
    """

    graph = _video_base_graph(
        model_config=model_config,
        diffusion_model=model_config.video_vace_diffusion_model,
        weight_dtype=model_config.video_vace_weight_dtype,
        loader=model_config.video_vace_loader,
        prompt=prompt,
        negative_prompt=negative_prompt,
    )
    graph["load_video"] = {
        "class_type": "LoadVideo",
        "inputs": {"file": control_video_name},
    }
    graph["video_components"] = {
        "class_type": "GetVideoComponents",
        "inputs": {"video": ["load_video", 0]},
    }
    graph["vace"] = {
        "class_type": "WanVaceToVideo",
        "inputs": {
            "positive": ["positive", 0],
            "negative": ["negative", 0],
            "vae": ["vae", 0],
            "width": width,
            "height": height,
            "length": length,
            "batch_size": 1,
            "strength": 1.0,
            "control_video": ["video_components", 0],
        },
    }
    graph.update(
        _video_tail(
            vace_node_id="vace",
            fps=fps,
            filename_prefix="parika/video_edit",
        )
    )
    graph["sampler"]["inputs"]["seed"] = seed

    return graph, _VIDEO_OUTPUT_NODE_ID
