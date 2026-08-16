"""
Unit tests for `parika.providers.comfyui.model_config.ComfyUIModelConfig`.

Focused on the video `weight_dtype`/`loader` configuration added
alongside the existing `*_diffusion_model` filenames: defaulting,
validation, independence from each other and from the filename, and
per-model resolution via `weight_dtype_for`/`loader_for`.
"""

from __future__ import annotations

import pytest

from parika.providers.comfyui.model_config import (
    VIDEO_T2V_MODEL_ID,
    VIDEO_VACE_MODEL_ID,
    ComfyUIModelConfig,
)


class TestWeightDtypeDefaults:
    def test_defaults_preserve_todays_behavior(self) -> None:
        config = ComfyUIModelConfig()

        assert config.video_t2v_weight_dtype == "default"
        assert config.video_vace_weight_dtype == "default"

    def test_diffusion_model_and_weight_dtype_are_independent_fields(self) -> None:
        # The FP8-scaled low-VRAM VACE checkpoint and its dtype can be
        # set together, purely through configuration.
        config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1_vace_1.3B_fp8_scaled.safetensors",
            video_vace_weight_dtype="fp8_e4m3fn",
        )

        assert config.video_vace_diffusion_model == (
            "wan2.1_vace_1.3B_fp8_scaled.safetensors"
        )
        assert config.video_vace_weight_dtype == "fp8_e4m3fn"

    def test_switching_back_to_fp16_model_requires_only_configuration(self) -> None:
        config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1_vace_1.3B_fp16.safetensors",
            video_vace_weight_dtype="default",
        )

        assert config.video_vace_diffusion_model == (
            "wan2.1_vace_1.3B_fp16.safetensors"
        )
        assert config.video_vace_weight_dtype == "default"


class TestWeightDtypeValidation:
    @pytest.mark.parametrize(
        "dtype", ["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"]
    )
    def test_accepts_every_native_unetloader_choice(self, dtype: str) -> None:
        t2v_config = ComfyUIModelConfig(video_t2v_weight_dtype=dtype)
        vace_config = ComfyUIModelConfig(video_vace_weight_dtype=dtype)

        assert t2v_config.video_t2v_weight_dtype == dtype
        assert vace_config.video_vace_weight_dtype == dtype

    def test_rejects_unsupported_t2v_weight_dtype(self) -> None:
        with pytest.raises(ValueError):
            ComfyUIModelConfig(video_t2v_weight_dtype="fp16")

    def test_rejects_unsupported_vace_weight_dtype(self) -> None:
        with pytest.raises(ValueError):
            ComfyUIModelConfig(video_vace_weight_dtype="not_a_real_dtype")


class TestWeightDtypeFor:
    def test_resolves_t2v_and_vace_independently(self) -> None:
        config = ComfyUIModelConfig(
            video_t2v_weight_dtype="default",
            video_vace_weight_dtype="fp8_e4m3fn",
        )

        assert config.weight_dtype_for(VIDEO_T2V_MODEL_ID) == "default"
        assert config.weight_dtype_for(VIDEO_VACE_MODEL_ID) == "fp8_e4m3fn"

    def test_returns_none_for_unrecognized_model_id(self) -> None:
        config = ComfyUIModelConfig()

        assert config.weight_dtype_for("not-a-real-model-id") is None


class TestLoaderDefaults:
    def test_defaults_to_native_preserving_todays_behavior(self) -> None:
        config = ComfyUIModelConfig()

        assert config.video_t2v_loader == "native"
        assert config.video_vace_loader == "native"


class TestLoaderValidation:
    @pytest.mark.parametrize("loader", ["native", "gguf"])
    def test_accepts_every_supported_loader(self, loader: str) -> None:
        t2v_config = ComfyUIModelConfig(
            video_t2v_loader=loader, video_t2v_weight_dtype="default"
        )
        vace_config = ComfyUIModelConfig(
            video_vace_loader=loader, video_vace_weight_dtype="default"
        )

        assert t2v_config.video_t2v_loader == loader
        assert vace_config.video_vace_loader == loader

    def test_rejects_unsupported_t2v_loader(self) -> None:
        with pytest.raises(ValueError):
            ComfyUIModelConfig(video_t2v_loader="not_a_real_loader")

    def test_rejects_unsupported_vace_loader(self) -> None:
        with pytest.raises(ValueError):
            ComfyUIModelConfig(video_vace_loader="not_a_real_loader")

    def test_gguf_loader_rejects_non_default_t2v_weight_dtype(self) -> None:
        with pytest.raises(ValueError):
            ComfyUIModelConfig(
                video_t2v_loader="gguf", video_t2v_weight_dtype="fp8_e4m3fn"
            )

    def test_gguf_loader_rejects_non_default_vace_weight_dtype(self) -> None:
        with pytest.raises(ValueError):
            ComfyUIModelConfig(
                video_vace_loader="gguf", video_vace_weight_dtype="fp8_e5m2"
            )

    def test_gguf_loader_accepts_default_weight_dtype(self) -> None:
        config = ComfyUIModelConfig(
            video_vace_loader="gguf", video_vace_weight_dtype="default"
        )

        assert config.video_vace_loader == "gguf"
        assert config.video_vace_weight_dtype == "default"


class TestLoaderModelIndependence:
    def test_model_filename_loader_and_weight_dtype_vary_independently(
        self,
    ) -> None:
        # Model filename, loader, and weight_dtype must be settable
        # in any combination the loader itself supports -- none is
        # inferred from another, and none is inferred from the
        # filename's extension.
        gguf_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )
        native_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1_vace_1.3B_fp8_scaled.safetensors",
            video_vace_loader="native",
            video_vace_weight_dtype="fp8_e4m3fn",
        )

        assert gguf_config.video_vace_diffusion_model == (
            "wan2.1-vace-1.3b-q4_k_m.gguf"
        )
        assert gguf_config.video_vace_loader == "gguf"
        assert native_config.video_vace_diffusion_model == (
            "wan2.1_vace_1.3B_fp8_scaled.safetensors"
        )
        assert native_config.video_vace_loader == "native"

    def test_filename_extension_does_not_determine_loader(self) -> None:
        # A ".gguf" filename configured with loader="native" is not
        # silently corrected to "gguf" (and vice versa) -- the
        # filename's extension has no bearing on validation or on the
        # resulting `video_vace_loader` value.
        config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="native",
            video_vace_weight_dtype="default",
        )

        assert config.video_vace_loader == "native"
        assert config.video_vace_diffusion_model == (
            "wan2.1-vace-1.3b-q4_k_m.gguf"
        )


class TestLoaderFor:
    def test_resolves_t2v_and_vace_independently(self) -> None:
        config = ComfyUIModelConfig(video_t2v_loader="native", video_vace_loader="gguf")

        assert config.loader_for(VIDEO_T2V_MODEL_ID) == "native"
        assert config.loader_for(VIDEO_VACE_MODEL_ID) == "gguf"

    def test_returns_none_for_unrecognized_model_id(self) -> None:
        config = ComfyUIModelConfig()

        assert config.loader_for("not-a-real-model-id") is None
