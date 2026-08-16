"""
Unit tests for `ComfyUIProviderDriver`, using a hand-written
`FakeComfyUITransport` double -- mirroring
`tests/providers/ollama/test_ollama_driver.py`'s own
`FakeOllamaTransport` shape exactly. No running ComfyUI server is
required.
"""

from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from parika.core.configuration.configuration import Configuration
from parika.core.logger.logger import Logger
from parika.core.provider_manager.generation_request import (
    GenerationOperation,
    GenerationRequest,
)
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider_model import ProviderModel
from parika.providers.comfyui.driver import ComfyUIProviderDriver
from parika.providers.comfyui.exceptions import (
    ComfyUIOutputNotFoundError,
    ComfyUIRequestError,
    ComfyUITimeoutError,
    ComfyUIWorkflowError,
)
from parika.providers.comfyui.model_config import (
    IMAGE_MODEL_ID,
    VIDEO_T2V_MODEL_ID,
    VIDEO_VACE_MODEL_ID,
    ComfyUIModelConfig,
)


class FakeComfyUITransport:
    """Deterministic ComfyUITransport test double, FIFO-queued per call kind."""

    def __init__(self) -> None:
        self.json_calls: list[tuple] = []
        self.upload_calls: list[tuple] = []
        self.fetch_calls: list[tuple] = []

        self._json_queue: list = []
        self._upload_queue: list = []
        self._fetch_queue: list = []

    def queue_json(self, response) -> None:
        self._json_queue.append(response)

    def queue_upload(self, response) -> None:
        self._upload_queue.append(response)

    def queue_fetch(self, response) -> None:
        self._fetch_queue.append(response)

    def request_json(self, method, url, *, payload, timeout):
        self.json_calls.append((method, url, payload, timeout))
        item = self._json_queue.pop(0)

        if isinstance(item, Exception):
            raise item

        return item

    def upload_media(self, url, filename, content, *, timeout):
        self.upload_calls.append((url, filename, content, timeout))
        item = self._upload_queue.pop(0)

        if isinstance(item, Exception):
            raise item

        return item

    def fetch_binary(self, url, *, timeout):
        self.fetch_calls.append((url, timeout))
        item = self._fetch_queue.pop(0)

        if isinstance(item, Exception):
            raise item

        return item


@pytest.fixture
def transport() -> FakeComfyUITransport:
    return FakeComfyUITransport()


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def driver(transport: FakeComfyUITransport, logger: Logger) -> ComfyUIProviderDriver:
    return ComfyUIProviderDriver(
        transport=transport,
        logger=logger,
        base_url="http://localhost:8188",
        connect_timeout_seconds=1.0,
        request_timeout_seconds=1.0,
        poll_interval_seconds=0.0,
        poll_timeout_seconds=1.0,
    )


def _completed_history(prompt_id: str, output_node_id: str, filename: str) -> dict:
    return {
        prompt_id: {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {
                output_node_id: {
                    "images": [{"filename": filename, "subfolder": "", "type": "output"}]
                }
            },
        }
    }


def _image_model() -> ProviderModel:
    return ProviderModel(
        id=IMAGE_MODEL_ID,
        name="qwen",
        capabilities=frozenset({ModelCapability.IMAGE_GENERATION}),
    )


def _t2v_model() -> ProviderModel:
    return ProviderModel(
        id=VIDEO_T2V_MODEL_ID,
        name="wan-t2v",
        capabilities=frozenset({ModelCapability.VIDEO_GENERATION}),
    )


def _vace_model() -> ProviderModel:
    return ProviderModel(
        id=VIDEO_VACE_MODEL_ID,
        name="wan-vace",
        capabilities=frozenset({ModelCapability.VIDEO_GENERATION}),
    )


class TestDiscoverModels:
    def test_returns_installed_models(self, driver, transport) -> None:
        transport.queue_json(
            [
                "qwen-image/qwen_image_fp8_e4m3fn.safetensors",
                "wan2.1_vace_1.3B_fp16.safetensors",
            ]
        )

        models = driver.discover_models()

        assert {m.id for m in models} == {IMAGE_MODEL_ID, VIDEO_VACE_MODEL_ID}
        assert transport.json_calls[0][1] == (
            "http://localhost:8188/models/diffusion_models"
        )
        # A native-only configuration (today's only behavior) makes
        # exactly the one HTTP call it always has -- no unconditional
        # extra GGUF listing request.
        assert len(transport.json_calls) == 1

    def test_gguf_configured_vace_model_queries_gguf_listing_too(
        self, transport, logger
    ) -> None:
        model_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )
        driver = ComfyUIProviderDriver(
            transport=transport,
            logger=logger,
            base_url="http://localhost:8188",
            connect_timeout_seconds=1.0,
            request_timeout_seconds=1.0,
            poll_interval_seconds=0.0,
            poll_timeout_seconds=1.0,
            model_config=model_config,
        )
        transport.queue_json(["qwen-image/qwen_image_fp8_e4m3fn.safetensors"])
        transport.queue_json(["wan2.1-vace-1.3b-q4_k_m.gguf"])

        models = driver.discover_models()

        assert {m.id for m in models} == {IMAGE_MODEL_ID, VIDEO_VACE_MODEL_ID}
        assert transport.json_calls[0][1] == (
            "http://localhost:8188/models/diffusion_models"
        )
        assert transport.json_calls[1][1] == (
            "http://localhost:8188/models/unet_gguf"
        )

    def test_gguf_listing_failure_omits_that_model_without_failing_discovery(
        self, transport, logger
    ) -> None:
        from parika.providers.comfyui.exceptions import ComfyUIResponseError

        model_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )
        driver = ComfyUIProviderDriver(
            transport=transport,
            logger=logger,
            base_url="http://localhost:8188",
            connect_timeout_seconds=1.0,
            request_timeout_seconds=1.0,
            poll_interval_seconds=0.0,
            poll_timeout_seconds=1.0,
            model_config=model_config,
        )
        transport.queue_json(["qwen-image/qwen_image_fp8_e4m3fn.safetensors"])
        transport.queue_json(ComfyUIResponseError("404"))

        models = driver.discover_models()

        # ComfyUI-GGUF missing/unreachable does not prevent discovery
        # of every other model -- exactly like an uninstalled
        # checkpoint file, the GGUF-configured model is simply not
        # offered.
        assert {m.id for m in models} == {IMAGE_MODEL_ID}


class TestCheckHealth:
    def test_reachable_server_reports_available(self, driver, transport) -> None:
        transport.queue_json(
            {"system": {"comfyui_version": "0.31.1"}}
        )

        health = driver.check_health()

        assert health.available is True
        assert "0.31.1" in health.message

    def test_connection_failure_reports_unavailable(self, driver, transport) -> None:
        from parika.providers.comfyui.exceptions import ComfyUIConnectionError

        transport.queue_json(ComfyUIConnectionError("refused"))

        health = driver.check_health()

        assert health.available is False


class TestExecuteRequestTypeValidation:
    def test_rejects_non_generation_request(self, driver) -> None:
        with pytest.raises(ComfyUIRequestError):
            driver.execute(_image_model(), ChatRequest(messages=()))


class TestImageGenerate:
    def test_submits_polls_and_returns_artifact(self, driver, transport) -> None:
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(_completed_history("p1", "save", "out.png"))
        transport.queue_fetch(b"png-bytes")

        request = GenerationRequest(
            operation=GenerationOperation.IMAGE_GENERATE,
            prompt="a red bicycle",
            width=512,
            height=512,
            seed=1,
        )
        result = driver.execute(_image_model(), request)

        assert len(result.artifacts) == 1
        assert result.artifacts[0].mime_type == "image/png"
        assert base64.b64decode(result.artifacts[0].content_base64) == b"png-bytes"

    def test_workflow_rejection_raises_workflow_error(self, driver, transport) -> None:
        transport.queue_json(
            {"prompt_id": None, "node_errors": {"unet": ["bad model"]}}
        )

        request = GenerationRequest(
            operation=GenerationOperation.IMAGE_GENERATE, prompt="x"
        )

        with pytest.raises(ComfyUIWorkflowError):
            driver.execute(_image_model(), request)

    def test_missing_prompt_id_raises_workflow_error(self, driver, transport) -> None:
        transport.queue_json({"node_errors": {}})

        request = GenerationRequest(
            operation=GenerationOperation.IMAGE_GENERATE, prompt="x"
        )

        with pytest.raises(ComfyUIWorkflowError):
            driver.execute(_image_model(), request)

    def test_execution_error_status_raises_workflow_error(
        self, driver, transport
    ) -> None:
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(
            {"p1": {"status": {"completed": False, "status_str": "error"}}}
        )

        request = GenerationRequest(
            operation=GenerationOperation.IMAGE_GENERATE, prompt="x"
        )

        with pytest.raises(ComfyUIWorkflowError):
            driver.execute(_image_model(), request)

    def test_never_completes_raises_timeout_error(self, driver, transport) -> None:
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json({"p1": {"status": {"completed": False}}})

        request = GenerationRequest(
            operation=GenerationOperation.IMAGE_GENERATE, prompt="x"
        )

        # Deterministically force the deadline to have already passed
        # after the single queued "not completed" poll, regardless of
        # real wall-clock speed: the first `monotonic()` call computes
        # the deadline, every subsequent call reports it as exceeded.
        with patch(
            "parika.providers.comfyui.driver.time.monotonic",
            side_effect=[0.0] + [100.0] * 10,
        ):
            with pytest.raises(ComfyUITimeoutError):
                driver.execute(_image_model(), request)

    def test_missing_output_raises_output_not_found_error(
        self, driver, transport
    ) -> None:
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(
            {"p1": {"status": {"completed": True}, "outputs": {"save": {}}}}
        )

        request = GenerationRequest(
            operation=GenerationOperation.IMAGE_GENERATE, prompt="x"
        )

        with pytest.raises(ComfyUIOutputNotFoundError):
            driver.execute(_image_model(), request)


class TestImageEdit:
    def test_uploads_source_image_before_submitting(self, driver, transport) -> None:
        transport.queue_upload({"name": "uploaded.png"})
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(_completed_history("p1", "save", "edited.png"))
        transport.queue_fetch(b"edited-bytes")

        source_base64 = base64.b64encode(b"source-image-bytes").decode("ascii")
        request = GenerationRequest(
            operation=GenerationOperation.IMAGE_EDIT,
            prompt="make it blue",
            input_images=(source_base64,),
        )
        result = driver.execute(_image_model(), request)

        assert transport.upload_calls[0][2] == b"source-image-bytes"
        assert base64.b64decode(result.artifacts[0].content_base64) == b"edited-bytes"

    def test_raises_when_no_input_image(self, driver) -> None:
        request = GenerationRequest(
            operation=GenerationOperation.IMAGE_EDIT, prompt="make it blue"
        )

        with pytest.raises(ComfyUIRequestError):
            driver.execute(_image_model(), request)


class TestVideoGenerate:
    def test_works_with_either_installed_video_model(self, driver, transport) -> None:
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(_completed_history("p1", "save", "out.mp4"))
        transport.queue_fetch(b"mp4-bytes")

        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_GENERATE,
            prompt="a river flowing",
            duration_seconds=1.0,
            fps=16.0,
        )
        result = driver.execute(_t2v_model(), request)

        assert result.artifacts[0].mime_type == "video/mp4"

    def test_unknown_model_raises_request_error(self, driver) -> None:
        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_GENERATE, prompt="x"
        )
        unknown_model = ProviderModel(
            id="comfyui/unknown", name="unknown", capabilities=frozenset()
        )

        with pytest.raises(ComfyUIRequestError):
            driver.execute(unknown_model, request)

    def test_submits_configured_weight_dtype_per_model(
        self, transport, logger
    ) -> None:
        # A configured `weight_dtype` must flow, unmodified, all the
        # way into the submitted ComfyUI workflow's `UNETLoader`
        # node, resolved independently per video model id.
        model_config = ComfyUIModelConfig(
            video_t2v_weight_dtype="fp8_e4m3fn_fast",
            video_vace_weight_dtype="fp8_e5m2",
        )
        driver = ComfyUIProviderDriver(
            transport=transport,
            logger=logger,
            base_url="http://localhost:8188",
            connect_timeout_seconds=1.0,
            request_timeout_seconds=1.0,
            poll_interval_seconds=0.0,
            poll_timeout_seconds=1.0,
            model_config=model_config,
        )
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(_completed_history("p1", "save", "out.mp4"))
        transport.queue_fetch(b"mp4-bytes")

        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_GENERATE,
            prompt="a river flowing",
            duration_seconds=1.0,
            fps=16.0,
        )
        driver.execute(_t2v_model(), request)

        submitted_graph = transport.json_calls[0][2]["prompt"]
        assert submitted_graph["unet"]["inputs"]["weight_dtype"] == "fp8_e4m3fn_fast"

        transport.queue_json({"prompt_id": "p2", "node_errors": {}})
        transport.queue_json(_completed_history("p2", "save", "out2.mp4"))
        transport.queue_fetch(b"mp4-bytes")

        driver.execute(_vace_model(), request)

        submitted_graph = transport.json_calls[2][2]["prompt"]
        assert submitted_graph["unet"]["inputs"]["weight_dtype"] == "fp8_e5m2"

    def test_submits_gguf_loader_node_when_configured(self, transport, logger) -> None:
        # A VACE model configured with loader="gguf" must submit an
        # `UnetLoaderGGUF` node (no `weight_dtype` input) instead of
        # `UNETLoader` -- purely through configuration, no code
        # change.
        model_config = ComfyUIModelConfig(
            video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
            video_vace_loader="gguf",
            video_vace_weight_dtype="default",
        )
        driver = ComfyUIProviderDriver(
            transport=transport,
            logger=logger,
            base_url="http://localhost:8188",
            connect_timeout_seconds=1.0,
            request_timeout_seconds=1.0,
            poll_interval_seconds=0.0,
            poll_timeout_seconds=1.0,
            model_config=model_config,
        )
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(_completed_history("p1", "save", "out.mp4"))
        transport.queue_fetch(b"mp4-bytes")

        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_GENERATE,
            prompt="a river flowing",
            duration_seconds=1.0,
            fps=16.0,
        )
        driver.execute(_vace_model(), request)

        submitted_graph = transport.json_calls[0][2]["prompt"]
        assert submitted_graph["unet"]["class_type"] == "UnetLoaderGGUF"
        assert submitted_graph["unet"]["inputs"] == {
            "unet_name": "wan2.1-vace-1.3b-q4_k_m.gguf"
        }

    def test_config_only_switch_between_fp8_fp16_and_gguf_vace(
        self, transport, logger
    ) -> None:
        # Rebuilding the driver with only a different
        # `ComfyUIModelConfig` (no Python source changes) must change
        # the submitted "unet" node accordingly, for every supported
        # configuration.
        def _submitted_unet_node(model_config: ComfyUIModelConfig) -> dict:
            driver = ComfyUIProviderDriver(
                transport=transport,
                logger=logger,
                base_url="http://localhost:8188",
                connect_timeout_seconds=1.0,
                request_timeout_seconds=1.0,
                poll_interval_seconds=0.0,
                poll_timeout_seconds=1.0,
                model_config=model_config,
            )
            transport.queue_json({"prompt_id": "p", "node_errors": {}})
            transport.queue_json(_completed_history("p", "save", "out.mp4"))
            transport.queue_fetch(b"mp4-bytes")

            request = GenerationRequest(
                operation=GenerationOperation.VIDEO_GENERATE,
                prompt="a river flowing",
                duration_seconds=1.0,
                fps=16.0,
            )
            driver.execute(_vace_model(), request)

            return transport.json_calls[-2][2]["prompt"]["unet"]

        fp8_unet = _submitted_unet_node(
            ComfyUIModelConfig(
                video_vace_diffusion_model="wan2.1_vace_1.3B_fp8_scaled.safetensors",
                video_vace_loader="native",
                video_vace_weight_dtype="fp8_e4m3fn",
            )
        )
        fp16_unet = _submitted_unet_node(
            ComfyUIModelConfig(
                video_vace_diffusion_model="wan2.1_vace_1.3B_fp16.safetensors",
                video_vace_loader="native",
                video_vace_weight_dtype="default",
            )
        )
        gguf_unet = _submitted_unet_node(
            ComfyUIModelConfig(
                video_vace_diffusion_model="wan2.1-vace-1.3b-q4_k_m.gguf",
                video_vace_loader="gguf",
                video_vace_weight_dtype="default",
            )
        )

        assert fp8_unet == {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "wan2.1_vace_1.3B_fp8_scaled.safetensors",
                "weight_dtype": "fp8_e4m3fn",
            },
        }
        assert fp16_unet == {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "wan2.1_vace_1.3B_fp16.safetensors",
                "weight_dtype": "default",
            },
        }
        assert gguf_unet == {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": "wan2.1-vace-1.3b-q4_k_m.gguf"},
        }


class TestVideoGenerateFromImage:
    def test_requires_vace_model(self, driver) -> None:
        source_base64 = base64.b64encode(b"start-frame").decode("ascii")
        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_GENERATE_FROM_IMAGE,
            prompt="animate this",
            input_images=(source_base64,),
        )

        with pytest.raises(ComfyUIRequestError):
            driver.execute(_t2v_model(), request)

    def test_succeeds_with_vace_model(self, driver, transport) -> None:
        transport.queue_upload({"name": "uploaded_ref.png"})
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(_completed_history("p1", "save", "out.mp4"))
        transport.queue_fetch(b"mp4-bytes")

        source_base64 = base64.b64encode(b"start-frame").decode("ascii")
        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_GENERATE_FROM_IMAGE,
            prompt="animate this",
            input_images=(source_base64,),
        )
        result = driver.execute(_vace_model(), request)

        assert result.artifacts[0].mime_type == "video/mp4"

    def test_raises_when_no_input_image(self, driver) -> None:
        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_GENERATE_FROM_IMAGE, prompt="animate"
        )

        with pytest.raises(ComfyUIRequestError):
            driver.execute(_vace_model(), request)


class TestVideoEdit:
    def test_requires_vace_model(self, driver) -> None:
        source_base64 = base64.b64encode(b"source-video").decode("ascii")
        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_EDIT,
            prompt="oil painting style",
            input_images=(source_base64,),
        )

        with pytest.raises(ComfyUIRequestError):
            driver.execute(_t2v_model(), request)

    def test_succeeds_with_vace_model(self, driver, transport) -> None:
        transport.queue_upload({"name": "uploaded_source.mp4"})
        transport.queue_json({"prompt_id": "p1", "node_errors": {}})
        transport.queue_json(_completed_history("p1", "save", "out.mp4"))
        transport.queue_fetch(b"edited-video-bytes")

        source_base64 = base64.b64encode(b"source-video").decode("ascii")
        request = GenerationRequest(
            operation=GenerationOperation.VIDEO_EDIT,
            prompt="oil painting style",
            input_images=(source_base64,),
        )
        result = driver.execute(_vace_model(), request)

        assert base64.b64decode(result.artifacts[0].content_base64) == (
            b"edited-video-bytes"
        )
