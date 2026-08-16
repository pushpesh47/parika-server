"""
Unit tests for `parika.providers.comfyui.workflows`.

These assert the *shape* of each generated ComfyUI API-format graph
(required nodes present, correctly wired to each other, and to the
caller-supplied prompt/size/seed values) without depending on any
running ComfyUI server. Every graph shape asserted here was
additionally verified against a live ComfyUI instance during
development (see the project's final report); these tests guard
against regressions in the pure graph-construction logic.
"""

from __future__ import annotations

import pytest

from parika.providers.comfyui import workflows
from parika.providers.comfyui.model_config import ComfyUIModelConfig


class TestBuildImageGenerateWorkflow:
    def test_graph_contains_expected_node_chain(self) -> None:
        graph, output_node_id = workflows.build_image_generate_workflow(
            model_config=ComfyUIModelConfig(),
            prompt="a red bicycle",
            negative_prompt="blurry",
            width=512,
            height=512,
            seed=42,
        )

        assert graph[output_node_id]["class_type"] == "SaveImage"
        assert graph["sampler"]["class_type"] == "KSampler"
        assert graph["sampler"]["inputs"]["seed"] == 42
        assert graph["sampler"]["inputs"]["denoise"] == 1.0
        assert graph["latent"]["inputs"]["width"] == 512
        assert graph["latent"]["inputs"]["height"] == 512
        # Image generation is unaffected by the video dtype
        # configuration added for `video_generate`/etc.
        assert graph["unet"]["inputs"]["weight_dtype"] == "default"

        positive_node_id = graph["sampler"]["inputs"]["positive"][0]
        assert graph[positive_node_id]["inputs"]["text"] == "a red bicycle"
        negative_node_id = graph["sampler"]["inputs"]["negative"][0]
        assert graph[negative_node_id]["inputs"]["text"] == "blurry"

        # No node in the image generate graph should reference a video
        # or edit-specific node type.
        class_types = {node["class_type"] for node in graph.values()}
        assert "LoadImage" not in class_types
        assert "VAEEncode" not in class_types

    def test_no_comfyui_node_data_leaks_ollama_style_types(self) -> None:
        graph, _ = workflows.build_image_generate_workflow(
            model_config=ComfyUIModelConfig(),
            prompt="a cat",
            negative_prompt="",
            width=512,
            height=512,
            seed=1,
        )
        # Every node is a plain dict -- never a dataclass/model
        # instance leaking a provider-independent type into a
        # ComfyUI-only structure.
        assert all(isinstance(node, dict) for node in graph.values())


class TestBuildImageEditWorkflow:
    def test_graph_encodes_source_image_and_partial_denoise(self) -> None:
        graph, output_node_id = workflows.build_image_edit_workflow(
            model_config=ComfyUIModelConfig(),
            prompt="make it blue",
            negative_prompt="",
            seed=7,
            input_image_name="uploaded_source.png",
        )

        assert graph["load_image"]["inputs"]["image"] == "uploaded_source.png"
        assert graph["encode_source"]["class_type"] == "VAEEncode"
        assert graph["encode_source"]["inputs"]["pixels"] == ["load_image", 0]

        assert graph["sampler"]["inputs"]["latent_image"] == ["encode_source", 0]
        assert 0.0 < graph["sampler"]["inputs"]["denoise"] < 1.0
        assert graph["sampler"]["inputs"]["seed"] == 7
        assert graph[output_node_id]["class_type"] == "SaveImage"


class TestBuildVideoGenerateWorkflow:
    def test_graph_omits_reference_and_control_video(self) -> None:
        graph, output_node_id = workflows.build_video_generate_workflow(
            model_config=ComfyUIModelConfig(),
            diffusion_model="Wan2.1/wan2.1_t2v_1.3B_bf16.safetensors",
            weight_dtype="default",
            loader="native",
            prompt="a paper boat floating",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=99,
        )

        assert graph["vace"]["class_type"] == "WanVaceToVideo"
        assert "reference_image" not in graph["vace"]["inputs"]
        assert "control_video" not in graph["vace"]["inputs"]
        assert graph["vace"]["inputs"]["length"] == 17
        assert graph["unet"]["inputs"]["unet_name"] == (
            "Wan2.1/wan2.1_t2v_1.3B_bf16.safetensors"
        )
        # Omitted/default dtype preserves today's behavior.
        assert graph["unet"]["inputs"]["weight_dtype"] == "default"
        assert graph["sampler"]["inputs"]["seed"] == 99
        assert graph["assemble"]["inputs"]["fps"] == 16.0
        assert graph[output_node_id]["class_type"] == "SaveVideo"

    def test_graph_uses_gguf_loader_node_when_configured(self) -> None:
        # A GGUF-configured T2V model must produce an `UnetLoaderGGUF`
        # node instead of `UNETLoader`, with no `weight_dtype` input
        # (that node has none), purely through the `loader` argument
        # -- independent of the diffusion model filename.
        graph, _ = workflows.build_video_generate_workflow(
            model_config=ComfyUIModelConfig(),
            diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            weight_dtype="default",
            loader="gguf",
            prompt="a paper boat floating",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=99,
        )

        assert graph["unet"]["class_type"] == "UnetLoaderGGUF"
        assert graph["unet"]["inputs"] == {
            "unet_name": "wan2.1-vace-1.3b-q4_k_m.gguf"
        }
        assert "weight_dtype" not in graph["unet"]["inputs"]

    def test_graph_uses_native_loader_node_by_default(self) -> None:
        graph, _ = workflows.build_video_generate_workflow(
            model_config=ComfyUIModelConfig(),
            diffusion_model="Wan2.1/wan2.1_t2v_1.3B_bf16.safetensors",
            weight_dtype="default",
            loader="native",
            prompt="a paper boat floating",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=99,
        )

        assert graph["unet"]["class_type"] == "UNETLoader"

    def test_graph_uses_configured_t2v_weight_dtype(self) -> None:
        # A T2V configuration requesting `fp8_e4m3fn` must produce a
        # UNETLoader with that exact `weight_dtype`, independent of
        # the diffusion model filename.
        graph, _ = workflows.build_video_generate_workflow(
            model_config=ComfyUIModelConfig(),
            diffusion_model="Wan2.1/wan2.1_t2v_1.3B_bf16.safetensors",
            weight_dtype="fp8_e4m3fn",
            loader="native",
            prompt="a paper boat floating",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=99,
        )

        assert graph["unet"]["inputs"]["unet_name"] == (
            "Wan2.1/wan2.1_t2v_1.3B_bf16.safetensors"
        )
        assert graph["unet"]["inputs"]["weight_dtype"] == "fp8_e4m3fn"

    def test_graph_wires_vace_outputs_into_sampler(self) -> None:
        graph, _ = workflows.build_video_generate_workflow(
            model_config=ComfyUIModelConfig(),
            diffusion_model="wan2.1_vace_1.3B_fp16.safetensors",
            weight_dtype="default",
            loader="native",
            prompt="a cube spinning",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=1,
        )

        assert graph["sampler"]["inputs"]["positive"] == ["vace", 0]
        assert graph["sampler"]["inputs"]["negative"] == ["vace", 1]
        assert graph["sampler"]["inputs"]["latent_image"] == ["vace", 2]
        assert graph["trim"]["inputs"]["trim_amount"] == ["vace", 3]


class TestBuildVideoGenerateFromImageWorkflow:
    def test_graph_wires_reference_image(self) -> None:
        graph, output_node_id = workflows.build_video_generate_from_image_workflow(
            model_config=ComfyUIModelConfig(),
            prompt="the cube rotates",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=5,
            reference_image_name="start.png",
        )

        assert graph["load_reference_image"]["inputs"]["image"] == "start.png"
        assert graph["vace"]["inputs"]["reference_image"] == [
            "load_reference_image",
            0,
        ]
        assert "control_video" not in graph["vace"]["inputs"]
        assert graph["unet"]["inputs"]["unet_name"] == (
            ComfyUIModelConfig().video_vace_diffusion_model
        )
        # Default `ComfyUIModelConfig` omits an explicit dtype, which
        # must preserve today's behavior.
        assert graph["unet"]["inputs"]["weight_dtype"] == (
            ComfyUIModelConfig().video_vace_weight_dtype
        )
        assert graph["unet"]["inputs"]["weight_dtype"] == "default"
        assert graph[output_node_id]["class_type"] == "SaveVideo"

    def test_graph_uses_configured_vace_model_and_weight_dtype(self) -> None:
        # A VACE configuration requesting the FP8-scaled checkpoint
        # with `weight_dtype="fp8_e4m3fn"` must flow straight through
        # to the UNETLoader, with no code change beyond configuration.
        fp8_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1_vace_1.3B_fp8_scaled.safetensors",
            video_vace_weight_dtype="fp8_e4m3fn",
        )

        graph, _ = workflows.build_video_generate_from_image_workflow(
            model_config=fp8_config,
            prompt="the cube rotates",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=5,
            reference_image_name="start.png",
        )

        assert graph["unet"]["inputs"]["unet_name"] == (
            "wan2.1_vace_1.3B_fp8_scaled.safetensors"
        )
        assert graph["unet"]["inputs"]["weight_dtype"] == "fp8_e4m3fn"

    def test_graph_switches_back_to_fp16_vace_model_through_config_only(
        self,
    ) -> None:
        # Switching the VACE model back to the original FP16
        # checkpoint with `weight_dtype="default"` is purely a
        # configuration change -- same builder, same graph shape.
        fp16_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1_vace_1.3B_fp16.safetensors",
            video_vace_weight_dtype="default",
        )

        graph, _ = workflows.build_video_generate_from_image_workflow(
            model_config=fp16_config,
            prompt="the cube rotates",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=5,
            reference_image_name="start.png",
        )

        assert graph["unet"]["inputs"]["unet_name"] == (
            "wan2.1_vace_1.3B_fp16.safetensors"
        )
        assert graph["unet"]["inputs"]["weight_dtype"] == "default"

    def test_graph_switches_to_gguf_vace_model_through_config_only(self) -> None:
        # Switching the VACE model to the installed GGUF checkpoint
        # with `video_vace_loader="gguf"` is purely a configuration
        # change: same builder, `UnetLoaderGGUF` instead of
        # `UNETLoader`, no `weight_dtype` input.
        gguf_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )

        graph, _ = workflows.build_video_generate_from_image_workflow(
            model_config=gguf_config,
            prompt="the cube rotates",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=5,
            reference_image_name="start.png",
        )

        assert graph["unet"]["class_type"] == "UnetLoaderGGUF"
        assert graph["unet"]["inputs"] == {
            "unet_name": "wan2.1-vace-1.3b-q4_k_m.gguf"
        }
        # Every other node/wiring is unchanged by the loader switch.
        assert graph["vace"]["inputs"]["reference_image"] == [
            "load_reference_image",
            0,
        ]

    def test_config_only_switch_native_fp8_fp16_gguf_changes_only_unet_node(
        self,
    ) -> None:
        # The single, most important invariant this feature adds:
        # switching *only* `ComfyUIModelConfig` between native FP8,
        # native FP16, and GGUF must change nothing about the
        # generated workflow except the "unet" node -- proving model
        # filename, loader, and dtype are independently
        # configuration-driven, with no Python source changes.
        fp8_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1_vace_1.3B_fp8_scaled.safetensors",
            video_vace_loader="native",
            video_vace_weight_dtype="fp8_e4m3fn",
        )
        fp16_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1_vace_1.3B_fp16.safetensors",
            video_vace_loader="native",
            video_vace_weight_dtype="default",
        )
        gguf_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )

        def _build(config: ComfyUIModelConfig) -> workflows.WorkflowGraph:
            graph, _ = workflows.build_video_generate_from_image_workflow(
                model_config=config,
                prompt="the cube rotates",
                negative_prompt="",
                width=320,
                height=320,
                length=17,
                fps=16.0,
                seed=5,
                reference_image_name="start.png",
            )
            return graph

        fp8_graph = _build(fp8_config)
        fp16_graph = _build(fp16_config)
        gguf_graph = _build(gguf_config)

        for graph in (fp8_graph, fp16_graph, gguf_graph):
            non_unet_nodes = {k: v for k, v in graph.items() if k != "unet"}
            assert non_unet_nodes == {
                k: v for k, v in fp8_graph.items() if k != "unet"
            }

        assert fp8_graph["unet"] == {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "wan2.1_vace_1.3B_fp8_scaled.safetensors",
                "weight_dtype": "fp8_e4m3fn",
            },
        }
        assert fp16_graph["unet"] == {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "wan2.1_vace_1.3B_fp16.safetensors",
                "weight_dtype": "default",
            },
        }
        assert gguf_graph["unet"] == {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": "wan2.1-vace-1.3b-q4_k_m.gguf"},
        }


class TestBuildVideoEditWorkflow:
    def test_graph_wires_control_video_from_source(self) -> None:
        graph, output_node_id = workflows.build_video_edit_workflow(
            model_config=ComfyUIModelConfig(),
            prompt="oil painting style",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=3,
            control_video_name="source.mp4",
        )

        assert graph["load_video"]["class_type"] == "LoadVideo"
        assert graph["load_video"]["inputs"]["file"] == "source.mp4"
        assert graph["video_components"]["class_type"] == "GetVideoComponents"
        assert graph["video_components"]["inputs"]["video"] == ["load_video", 0]
        assert graph["vace"]["inputs"]["control_video"] == ["video_components", 0]
        assert "reference_image" not in graph["vace"]["inputs"]
        assert graph["unet"]["inputs"]["weight_dtype"] == (
            ComfyUIModelConfig().video_vace_weight_dtype
        )
        assert graph[output_node_id]["class_type"] == "SaveVideo"

    def test_graph_uses_gguf_loader_when_configured(self) -> None:
        gguf_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )

        graph, _ = workflows.build_video_edit_workflow(
            model_config=gguf_config,
            prompt="oil painting style",
            negative_prompt="",
            width=320,
            height=320,
            length=17,
            fps=16.0,
            seed=3,
            control_video_name="source.mp4",
        )

        assert graph["unet"]["class_type"] == "UnetLoaderGGUF"
        assert graph["unet"]["inputs"] == {
            "unet_name": "wan2.1-vace-1.3b-q4_k_m.gguf"
        }
        assert graph["vace"]["inputs"]["control_video"] == ["video_components", 0]


class TestDiffusionModelLoaderNode:
    def test_rejects_unrecognized_loader_defensively(self) -> None:
        # ComfyUIModelConfig already validates `loader` at
        # construction time; this only guards against an internal
        # inconsistency if that invariant is ever violated.
        with pytest.raises(ValueError):
            workflows._diffusion_model_loader_node(
                loader="not_a_real_loader",
                diffusion_model="whatever.safetensors",
                weight_dtype="default",
            )
