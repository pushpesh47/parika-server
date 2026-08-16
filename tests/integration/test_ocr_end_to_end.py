"""
End-to-end integration test for OCR support (Option A): the general
chat model delegates to `ocr.extract_text` through ordinary native
tool calling, which reaches the existing, unmodified Filesystem
Capability and a Provider-backed `ocr.provider_extract_text` Goal that Model
Selection routes to an OCR-specialized model (`glm-ocr`), exactly
mirroring `StandardCodingAgent`'s existing `coding.execute_task` ->
`coding.plan_change` shape.

Uses a real `ParikaRuntime` (real Brain, Planner, CapabilityRegistry,
CapabilityResolver, Model Selection Framework, ToolManager, Filesystem
Module, Ollama provider driver) with only the outermost Ollama HTTP
transport faked, so the full

    User -> chat.respond -> General Model -> Tool Call ->
    ocr.extract_text -> filesystem.read -> ocr.provider_extract_text -> Planner ->
    ExecutionRequirements -> glm-ocr selected -> Ollama Provider ->
    OCR Result -> General Model -> Final Response

path is verified end to end against the actual `/api/chat` HTTP
payloads sent, never against a synthetic slice of the pipeline.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.interfaces.session import InterfaceSession


class _OcrScriptedOllamaTransport:
    """
    Scripts `/api/tags`/`/api/show` to discover two models -- an
    ordinary general-chat model and `glm-ocr` -- exactly like
    `tests/providers/ollama/test_glm_ocr_regression.py`'s realistic
    fixtures, and records every `/api/chat` payload sent so the test
    can inspect them directly (which model each call targeted, and
    whether the image was actually transmitted).
    """

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
                    {"model": "glm-ocr:latest"},
                ]
            }

        if url.endswith("/api/show"):
            model = (payload or {}).get("model", "")

            if model.startswith("glm-ocr"):
                return {
                    "capabilities": ["completion", "vision"],
                    "model_info": {"glm4.context_length": 8192},
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
def transport() -> _OcrScriptedOllamaTransport:
    return _OcrScriptedOllamaTransport()


@pytest.fixture
def runtime(transport: _OcrScriptedOllamaTransport, tmp_path):
    runtime = build_default_runtime(
        ollama_transport=transport, data_directory=tmp_path / "data"
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


class TestOcrEndToEnd:
    def test_extract_aadhaar_details_via_native_tool_calling(
        self, runtime, transport: _OcrScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "p1.png"
        image_bytes = b"\x89PNG\r\n\x1a\n-fake-aadhaar-card-image-bytes-"
        image_path.write_bytes(image_bytes)

        instruction = "Extract the Aadhaar Number, Name, DOB and Address"
        recognized_text = (
            "Aadhaar Number: 1234 5678 9012\n"
            "Name: Test User\n"
            "DOB: 01-01-1990\n"
            "Address: 123 Test Street"
        )

        # 1st /api/chat: the general chat model reasons over the raw
        # user message and decides, through ordinary native tool
        # calling, to call `ocr_extract_text` -- exactly as it already
        # decides to call `filesystem_read` for a plain file request.
        transport.queue_chat_response(
            _tool_call_answer(
                "ocr_extract_text",
                {"path": str(image_path), "instruction": instruction},
            )
        )
        # 2nd /api/chat: the nested, Provider-backed `ocr.provider_extract_text`
        # Goal, served by whichever model Model Selection chose for
        # CapabilityCategory.OCR.
        transport.queue_chat_response(_text_answer(recognized_text))
        # 3rd /api/chat: the general chat model's final answer, after
        # receiving the tool result.
        transport.queue_chat_response(
            _text_answer(f"Here are the details:\n{recognized_text}")
        )

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(
            f"Extract the Aadhaar Number, Name, DOB and Address from {image_path}"
        )

        assert result.succeeded
        assert len(transport.chat_payloads) == 3

        outer_first, ocr_call, outer_final = transport.chat_payloads

        # Model Selection routed the outer chat.respond turns to the
        # general chat model...
        assert outer_first["model"] == "qwen3-coder-next:latest"
        assert outer_final["model"] == "qwen3-coder-next:latest"

        # ...and the inner ocr.provider_extract_text Goal specifically to glm-ocr
        # (CapabilityCategory.OCR -> ModelCapability.VISION ->
        # TaskCategory.OCR -> required_specializations={"ocr"} ->
        # filtering.py's specialization filter, entirely unmodified
        # code -- see test_glm_ocr_regression.py for the same proof in
        # isolation).
        assert ocr_call["model"] == "glm-ocr:latest"

        # The image was actually transmitted to the OCR model, through
        # Ollama's own, provider-specific `images` wire field.
        ocr_message = ocr_call["messages"][0]
        assert ocr_message["role"] == "user"
        assert ocr_message["content"] == instruction
        assert ocr_message["images"] == [
            base64.b64encode(image_bytes).decode("ascii")
        ]

        # No image/base64 ever reaches the outer model's own request.
        assert all("images" not in m for m in outer_first["messages"])
        assert all("images" not in m for m in outer_final["messages"])

        # The final response reaching the user contains the recognized
        # fields.
        assert result.chat_response is not None
        assert "1234 5678 9012" in result.chat_response.message.content
        assert "Test User" in result.chat_response.message.content
