"""
End-to-end integration tests for the Vision Module's Phase 1-5
extensions: the general chat model delegates to one of the new
deterministic-first `vision.*` TOOL Capabilities through ordinary
native tool calling. Uses a real `ParikaRuntime` (real Brain, Planner,
CapabilityRegistry, Model Selection Framework, ToolManager, Filesystem
Module, Ollama provider driver) with only the outermost Ollama HTTP
transport faked, exactly mirroring
`tests/integration/test_vision_end_to_end.py`'s own shape.

Covers three representative shapes:
- A purely deterministic editing Capability (`vision.crop_image`):
  never reaches a Vision model at all -- only two `/api/chat` calls
  (the tool-call decision, then the final answer), proving the
  "compute optimization" requirement end to end, not merely in a
  unit test with a fake Brain.
- A purely deterministic analysis Capability (`vision.detect_blur`):
  same two-call shape.
- A deterministic-first Capability escalating to its Provider-backed
  Capability (`vision.compare_images` with an explicit `instruction`):
  three `/api/chat` calls, the middle one routed to the Vision model
  with *both* images attached in one message.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from PIL import Image, ImageDraw

from parika.core.permission_manager.workspace_permission_scope import (
    WorkspacePermissionScope,
)
from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.interfaces.session import InterfaceSession


class _AutoApprovePermissionPrompt:
    """Auto-approves every workspace permission request for the current
    session, so file-writing Capabilities (e.g. `vision.crop_image`)
    can be exercised against a real `tmp_path` workspace without an
    interactive prompt."""

    def request_decision(self, *, workspace, operation, reason) -> WorkspacePermissionScope:
        return WorkspacePermissionScope.SESSION


class _ScriptedOllamaTransport:
    def __init__(self) -> None:
        self._chat_queue: list[dict[str, Any]] = []
        self.chat_payloads: list[dict[str, Any]] = []

    def queue_chat_response(self, response: dict[str, Any]) -> None:
        self._chat_queue.append(response)

    def request_json(self, method, url, *, payload, timeout) -> dict[str, Any]:
        if url.endswith("/api/tags"):
            return {
                "models": [
                    {"model": "qwen3-coder-next:latest"},
                    {"model": "minicpm-v4.5:latest"},
                ]
            }

        if url.endswith("/api/show"):
            model = (payload or {}).get("model", "")

            if model.startswith("minicpm-v4.5"):
                return {
                    "capabilities": ["completion", "vision"],
                    "model_info": {"minicpm.context_length": 8192},
                }

            return {
                "capabilities": ["completion", "tools"],
                "model_info": {"qwen3.context_length": 40960},
            }

        if url.endswith("/api/version"):
            return {"version": "0.0.0-test"}

        if url.endswith("/api/chat"):
            self.chat_payloads.append(dict(payload or {}))
            return self._chat_queue.pop(0)

        return {}

    def stream_lines(self, method, url, *, payload, timeout):
        return iter(())


@pytest.fixture
def transport() -> _ScriptedOllamaTransport:
    return _ScriptedOllamaTransport()


@pytest.fixture
def runtime(transport: _ScriptedOllamaTransport, tmp_path):
    runtime = build_default_runtime(
        ollama_transport=transport,
        data_directory=tmp_path / "data",
        workspace_permission_prompt=_AutoApprovePermissionPrompt(),
    )
    yield runtime
    shutdown_runtime(runtime)


def _tool_call_answer(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        },
        "done": True,
    }


def _text_answer(text: str) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": text}, "done": True}


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    import io

    image = Image.new("RGB", (120, 90), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class TestVisionCropImageEndToEnd:
    def test_crop_image_never_calls_a_vision_model(
        self, runtime, transport: _ScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "photo.png"
        image_path.write_bytes(_png_bytes((10, 20, 30)))

        transport.queue_chat_response(
            _tool_call_answer(
                "vision_crop_image",
                {
                    "path": str(image_path),
                    "x": 0,
                    "y": 0,
                    "width": 50,
                    "height": 40,
                },
            )
        )
        transport.queue_chat_response(_text_answer("Cropped the image."))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Crop {image_path} to 50x40 from the top-left")

        assert result.succeeded
        # Only two /api/chat calls -- the tool-call decision and the
        # final answer -- since this Capability never reaches a
        # Vision model at all.
        assert len(transport.chat_payloads) == 2
        assert all(m["model"] == "qwen3-coder-next:latest" for m in transport.chat_payloads)

        output_path = tmp_path / "photo_cropped.png"
        assert output_path.exists()

        with Image.open(output_path) as cropped:
            assert cropped.size == (50, 40)


class TestVisionDetectBlurEndToEnd:
    def test_detect_blur_never_calls_a_vision_model(
        self, runtime, transport: _ScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "sharp.png"
        image = Image.new("L", (200, 200), color=255)
        draw = ImageDraw.Draw(image)
        for x in range(0, 200, 8):
            draw.line([(x, 0), (x, 200)], fill=0, width=2)
        image.convert("RGB").save(image_path)

        transport.queue_chat_response(
            _tool_call_answer("vision_detect_blur", {"path": str(image_path)})
        )
        transport.queue_chat_response(_text_answer("The image is sharp."))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Is {image_path} blurry?")

        assert result.succeeded
        assert len(transport.chat_payloads) == 2


class TestVisionCompareImagesEscalationEndToEnd:
    def test_instruction_escalates_to_vision_model_with_both_images(
        self, runtime, transport: _ScriptedOllamaTransport, tmp_path
    ) -> None:
        path_a = tmp_path / "a.png"
        path_b = tmp_path / "b.png"
        bytes_a = _png_bytes((255, 255, 255))
        bytes_b = _png_bytes((0, 0, 0))
        path_a.write_bytes(bytes_a)
        path_b.write_bytes(bytes_b)

        explanation = "The two images have opposite brightness."

        transport.queue_chat_response(
            _tool_call_answer(
                "vision_compare_images",
                {
                    "path_a": str(path_a),
                    "path_b": str(path_b),
                    "instruction": "Explain why these differ.",
                },
            )
        )
        transport.queue_chat_response(_text_answer(explanation))
        transport.queue_chat_response(_text_answer(f"Comparison: {explanation}"))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(
            f"Compare {path_a} and {path_b} and explain the difference"
        )

        assert result.succeeded
        assert len(transport.chat_payloads) == 3

        outer_first, vision_call, outer_final = transport.chat_payloads

        assert outer_first["model"] == "qwen3-coder-next:latest"
        assert vision_call["model"] == "minicpm-v4.5:latest"
        assert outer_final["model"] == "qwen3-coder-next:latest"

        vision_message = vision_call["messages"][0]
        assert vision_message["images"] == [
            base64.b64encode(bytes_a).decode("ascii"),
            base64.b64encode(bytes_b).decode("ascii"),
        ]

        assert result.chat_response is not None
        assert "opposite brightness" in result.chat_response.message.content
