"""
Unit tests for `parika.providers.comfyui.discovery`.
"""

from __future__ import annotations

from parika.core.provider_manager.model_capability import ModelCapability
from parika.providers.comfyui.discovery import (
    discover_models,
    model_listing_path_for_loader,
)
from parika.providers.comfyui.model_config import (
    IMAGE_MODEL_ID,
    VIDEO_T2V_MODEL_ID,
    VIDEO_VACE_MODEL_ID,
    ComfyUIModelConfig,
)


def test_returns_no_models_when_nothing_installed() -> None:
    models = discover_models(
        installed_diffusion_models=[], model_config=ComfyUIModelConfig()
    )

    assert models == ()


def test_returns_only_installed_models() -> None:
    config = ComfyUIModelConfig()
    models = discover_models(
        installed_diffusion_models=[config.image_diffusion_model],
        model_config=config,
    )

    assert [m.id for m in models] == [IMAGE_MODEL_ID]
    assert ModelCapability.IMAGE_GENERATION in models[0].capabilities
    assert "image_generation" in models[0].specializations
    assert "image_editing" in models[0].specializations


def test_returns_all_models_when_all_installed() -> None:
    config = ComfyUIModelConfig()
    models = discover_models(
        installed_diffusion_models=[
            config.image_diffusion_model,
            config.video_t2v_diffusion_model,
            config.video_vace_diffusion_model,
        ],
        model_config=config,
    )

    assert {m.id for m in models} == {
        IMAGE_MODEL_ID,
        VIDEO_T2V_MODEL_ID,
        VIDEO_VACE_MODEL_ID,
    }


def test_t2v_model_lacks_conditioning_specializations() -> None:
    config = ComfyUIModelConfig()
    models = discover_models(
        installed_diffusion_models=[config.video_t2v_diffusion_model],
        model_config=config,
    )

    t2v_model = models[0]
    assert t2v_model.id == VIDEO_T2V_MODEL_ID
    assert "video_generation" in t2v_model.specializations
    assert "video_generation_from_image" not in t2v_model.specializations
    assert "video_editing" not in t2v_model.specializations


def test_vace_model_declares_every_video_specialization() -> None:
    config = ComfyUIModelConfig()
    models = discover_models(
        installed_diffusion_models=[config.video_vace_diffusion_model],
        model_config=config,
    )

    vace_model = models[0]
    assert vace_model.id == VIDEO_VACE_MODEL_ID
    assert vace_model.specializations == {
        "video_generation",
        "video_generation_from_image",
        "video_editing",
    }


def test_unrelated_installed_models_are_ignored() -> None:
    models = discover_models(
        installed_diffusion_models=["some_other_model.safetensors"],
        model_config=ComfyUIModelConfig(),
    )

    assert models == ()


class TestModelListingPathForLoader:
    def test_native_loader_uses_diffusion_models_listing(self) -> None:
        assert model_listing_path_for_loader("native") == (
            "/models/diffusion_models"
        )

    def test_gguf_loader_uses_unet_gguf_listing(self) -> None:
        assert model_listing_path_for_loader("gguf") == "/models/unet_gguf"


class TestGgufModelDiscovery:
    def test_gguf_configured_vace_model_is_checked_against_gguf_listing(
        self,
    ) -> None:
        # A GGUF-configured VACE model must be resolved against
        # `installed_gguf_models`, not `installed_diffusion_models`
        # (ComfyUI-GGUF registers `.gguf` checkpoints under a
        # distinct folder listing).
        config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )

        models = discover_models(
            installed_diffusion_models=[],
            installed_gguf_models=["wan2.1-vace-1.3b-q4_k_m.gguf"],
            model_config=config,
        )

        assert [m.id for m in models] == [VIDEO_VACE_MODEL_ID]

    def test_gguf_configured_model_not_in_gguf_listing_is_not_offered(self) -> None:
        # Present in the native listing but configured for the GGUF
        # loader must still not be offered: the loader, not the
        # filename, decides which listing is authoritative.
        config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )

        models = discover_models(
            installed_diffusion_models=["wan2.1-vace-1.3b-q4_k_m.gguf"],
            installed_gguf_models=[],
            model_config=config,
        )

        assert models == ()

    def test_native_configured_model_ignores_gguf_listing(self) -> None:
        # A native-configured model present only in the GGUF listing
        # (e.g. leftover/unrelated data) must still not be offered.
        config = ComfyUIModelConfig()

        models = discover_models(
            installed_diffusion_models=[],
            installed_gguf_models=[config.video_vace_diffusion_model],
            model_config=config,
        )

        assert models == ()

    def test_t2v_and_vace_loaders_are_resolved_independently(self) -> None:
        config = ComfyUIModelConfig(
            video_t2v_loader="native",
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )

        models = discover_models(
            installed_diffusion_models=[config.video_t2v_diffusion_model],
            installed_gguf_models=["wan2.1-vace-1.3b-q4_k_m.gguf"],
            model_config=config,
        )

        assert {m.id for m in models} == {VIDEO_T2V_MODEL_ID, VIDEO_VACE_MODEL_ID}
