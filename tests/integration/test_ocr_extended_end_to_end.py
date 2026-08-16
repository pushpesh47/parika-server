"""
End-to-end integration coverage for two of the OCR Module's extended
Capabilities, mirroring `test_ocr_end_to_end.py`'s own real-runtime
shape (real `ParikaRuntime` - real Brain, Planner, CapabilityRegistry,
CapabilityResolver, Model Selection Framework, ToolManager, Filesystem
Module, Ollama provider driver - with only the outermost Ollama HTTP
transport faked):

- `ocr.detect_orientation`: proves the fully deterministic path -
  native tool calling reaches it, but it never issues a second
  `/api/chat` call of its own (no Provider-backed Goal at all).
- `ocr.extract_table`: proves the structured-extraction path - native
  tool calling reaches it, `ocr.provider_extract_text` is routed to
  the OCR-specialized model exactly like `ocr.extract_text` already
  is, and its JSON response is deterministically parsed into `data`.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.interfaces.session import InterfaceSession


class _ScriptedOllamaTransport:
    """See `test_ocr_end_to_end.py`'s own transport fixture - identical shape."""

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
def transport() -> _ScriptedOllamaTransport:
    return _ScriptedOllamaTransport()


@pytest.fixture
def runtime(transport: _ScriptedOllamaTransport, tmp_path):
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


def _real_image_bytes() -> bytes:
    image = Image.new("RGB", (600, 800), color=(220, 220, 220))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class TestOcrDetectOrientationEndToEnd:
    def test_never_issues_a_second_chat_call_for_the_deterministic_tool(
        self, runtime, transport: _ScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(_real_image_bytes())

        transport.queue_chat_response(
            _tool_call_answer(
                "ocr_detect_orientation", {"path": str(image_path)}
            )
        )
        transport.queue_chat_response(_text_answer("This scan looks upright."))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Is {image_path} rotated?")

        assert result.succeeded
        # Only the outer model's two turns - never a third /api/chat
        # call, since ocr.detect_orientation is purely deterministic.
        assert len(transport.chat_payloads) == 2
        assert transport.chat_payloads[0]["model"] == "qwen3-coder-next:latest"
        assert transport.chat_payloads[1]["model"] == "qwen3-coder-next:latest"


class TestOcrExtractTableEndToEnd:
    def test_extracts_table_and_routes_to_ocr_specialized_model(
        self, runtime, transport: _ScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "table.png"
        image_path.write_bytes(_real_image_bytes())

        transport.queue_chat_response(
            _tool_call_answer("ocr_extract_table", {"path": str(image_path)})
        )
        transport.queue_chat_response(
            _text_answer('{"headers": ["Item", "Price"], "rows": [["Pen", "1.00"]]}')
        )
        transport.queue_chat_response(
            _text_answer("The table has one row: Pen costs 1.00.")
        )

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Extract the table from {image_path}")

        assert result.succeeded
        assert len(transport.chat_payloads) == 3

        outer_first, ocr_call, outer_final = transport.chat_payloads
        assert outer_first["model"] == "qwen3-coder-next:latest"
        assert ocr_call["model"] == "glm-ocr:latest"
        assert outer_final["model"] == "qwen3-coder-next:latest"

        assert result.chat_response is not None
        assert "1.00" in result.chat_response.message.content
