"""
End-to-end integration tests for the Vision Capability family (Option
A): the general chat model delegates to a `vision.*` TOOL Capability
through ordinary native tool calling, which reaches the existing,
unmodified Filesystem Capability and a Provider-backed `vision.*`
Goal that Model Selection routes to a Vision-specialized model
(`minicpm-v4.5`), exactly mirroring `tests/integration
/test_ocr_end_to_end.py`'s own OCR shape.

Uses a real `ParikaRuntime` (real Brain, Planner, CapabilityRegistry,
CapabilityResolver, Model Selection Framework, ToolManager, Filesystem
Module, Ollama provider driver) with only the outermost Ollama HTTP
transport faked, so the full

    User -> chat.respond -> General Model -> Tool Call ->
    vision.describe_image -> filesystem.read -> vision.provider_describe_image ->
    Planner -> ExecutionRequirements -> minicpm-v4.5 selected ->
    Ollama Provider -> Vision Result -> General Model -> Final
    Response

path is verified end to end against the actual `/api/chat` HTTP
payloads sent, never against a synthetic slice of the pipeline.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from parika.interfaces.runtime import build_default_runtime, shutdown_runtime
from parika.interfaces.session import InterfaceSession


class _VisionScriptedOllamaTransport:
    """
    Scripts `/api/tags`/`/api/show` to discover two models -- an
    ordinary general-chat model and `minicpm-v4.5` -- exactly like
    `tests/integration/test_ocr_end_to_end.py`'s own
    `_OcrScriptedOllamaTransport`, and records every `/api/chat`
    payload sent so the test can inspect them directly.
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
def transport() -> _VisionScriptedOllamaTransport:
    return _VisionScriptedOllamaTransport()


@pytest.fixture
def runtime(transport: _VisionScriptedOllamaTransport, tmp_path):
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


class TestVisionDescribeImageEndToEnd:
    def test_describe_image_via_native_tool_calling(
        self, runtime, transport: _VisionScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "dog.png"
        image_bytes = b"\x89PNG\r\n\x1a\n-fake-dog-photo-image-bytes-"
        image_path.write_bytes(image_bytes)

        description = "A golden retriever sitting on a green lawn."

        # 1st /api/chat: the general chat model reasons over the raw
        # user message and decides, through ordinary native tool
        # calling, to call `vision_describe_image`.
        transport.queue_chat_response(
            _tool_call_answer(
                "vision_describe_image",
                {"path": str(image_path)},
            )
        )
        # 2nd /api/chat: the nested, Provider-backed `vision.provider_describe_image`
        # Goal, served by whichever model Model Selection chose for
        # CapabilityCategory.VISION.
        transport.queue_chat_response(_text_answer(description))
        # 3rd /api/chat: the general chat model's final answer.
        transport.queue_chat_response(_text_answer(f"Here you go: {description}"))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Describe this image: {image_path}")

        assert result.succeeded
        assert len(transport.chat_payloads) == 3

        outer_first, vision_call, outer_final = transport.chat_payloads

        # Model Selection routed the outer chat.respond turns to the
        # general chat model...
        assert outer_first["model"] == "qwen3-coder-next:latest"
        assert outer_final["model"] == "qwen3-coder-next:latest"

        # ...and the inner vision.provider_describe_image Goal specifically to
        # minicpm-v4.5 (CapabilityCategory.VISION ->
        # ModelCapability.VISION -> TaskCategory.VISION_UNDERSTANDING
        # -> required_specializations={"vision_understanding"} ->
        # filtering.py's specialization filter, entirely unmodified
        # code, satisfied through the Local Curated Override in
        # `parika.core.semantics.model_knowledge`).
        assert vision_call["model"] == "minicpm-v4.5:latest"

        # The image was actually transmitted to the Vision model,
        # through Ollama's own, provider-specific `images` wire field.
        vision_message = vision_call["messages"][0]
        assert vision_message["role"] == "user"
        assert vision_message["images"] == [
            base64.b64encode(image_bytes).decode("ascii")
        ]

        # No image/base64 ever reaches the outer model's own request.
        assert all("images" not in m for m in outer_first["messages"])
        assert all("images" not in m for m in outer_final["messages"])

        # The final response reaching the user contains the
        # analysis.
        assert result.chat_response is not None
        assert "golden retriever" in result.chat_response.message.content


class TestVisionAnswerQuestionEndToEnd:
    def test_answer_question_via_native_tool_calling(
        self, runtime, transport: _VisionScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "car.png"
        image_bytes = b"\x89PNG\r\n\x1a\n-fake-car-photo-image-bytes-"
        image_path.write_bytes(image_bytes)

        question = "What color is the car?"
        answer = "The car is red."

        transport.queue_chat_response(
            _tool_call_answer(
                "vision_answer_question",
                {"path": str(image_path), "question": question},
            )
        )
        transport.queue_chat_response(_text_answer(answer))
        transport.queue_chat_response(_text_answer(answer))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"{question} ({image_path})")

        assert result.succeeded
        assert len(transport.chat_payloads) == 3

        _, vqa_call, _ = transport.chat_payloads

        assert vqa_call["model"] == "minicpm-v4.5:latest"
        assert vqa_call["messages"][0]["content"] == question
        assert vqa_call["messages"][0]["images"] == [
            base64.b64encode(image_bytes).decode("ascii")
        ]

        assert result.chat_response is not None
        assert "red" in result.chat_response.message.content


class TestVisionDetectObjectsEndToEnd:
    def test_detect_objects_via_native_tool_calling(
        self, runtime, transport: _VisionScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "street.png"
        image_bytes = b"\x89PNG\r\n\x1a\n-fake-street-photo-image-bytes-"
        image_path.write_bytes(image_bytes)

        detection = "3 people, 1 bicycle, 2 cars."

        transport.queue_chat_response(
            _tool_call_answer(
                "vision_detect_objects",
                {"path": str(image_path), "instruction": "Count all people"},
            )
        )
        transport.queue_chat_response(_text_answer(detection))
        transport.queue_chat_response(_text_answer(f"I found: {detection}"))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Count the people in {image_path}")

        assert result.succeeded

        _, detect_call, _ = transport.chat_payloads
        assert detect_call["model"] == "minicpm-v4.5:latest"
        assert detect_call["messages"][0]["content"] == "Count all people"

        assert result.chat_response is not None
        assert "3 people" in result.chat_response.message.content


class TestVisionAnalyzeChartEndToEnd:
    def test_analyze_chart_via_native_tool_calling(
        self, runtime, transport: _VisionScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "chart.png"
        image_bytes = b"\x89PNG\r\n\x1a\n-fake-chart-image-bytes-"
        image_path.write_bytes(image_bytes)

        chart_analysis = (
            "A line chart showing revenue growth from Q1 to Q4, "
            "peaking in Q4 at $5M."
        )

        transport.queue_chat_response(
            _tool_call_answer(
                "vision_analyze_chart",
                {"path": str(image_path)},
            )
        )
        transport.queue_chat_response(_text_answer(chart_analysis))
        transport.queue_chat_response(_text_answer(chart_analysis))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Explain this chart: {image_path}")

        assert result.succeeded

        _, chart_call, _ = transport.chat_payloads
        assert chart_call["model"] == "minicpm-v4.5:latest"

        assert result.chat_response is not None
        assert "revenue growth" in result.chat_response.message.content


class TestVisionAnalyzeDiagramEndToEnd:
    def test_analyze_diagram_via_native_tool_calling(
        self, runtime, transport: _VisionScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "diagram.png"
        image_bytes = b"\x89PNG\r\n\x1a\n-fake-diagram-image-bytes-"
        image_path.write_bytes(image_bytes)

        diagram_analysis = (
            "A three-tier architecture diagram: client, API server, "
            "and database, connected left to right."
        )

        transport.queue_chat_response(
            _tool_call_answer(
                "vision_analyze_diagram",
                {"path": str(image_path)},
            )
        )
        transport.queue_chat_response(_text_answer(diagram_analysis))
        transport.queue_chat_response(_text_answer(diagram_analysis))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Explain this architecture diagram: {image_path}")

        assert result.succeeded

        _, diagram_call, _ = transport.chat_payloads
        assert diagram_call["model"] == "minicpm-v4.5:latest"

        assert result.chat_response is not None
        assert "three-tier architecture" in result.chat_response.message.content


class TestVisionAnalyzeUiEndToEnd:
    def test_analyze_ui_via_native_tool_calling(
        self, runtime, transport: _VisionScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "screenshot.png"
        image_bytes = b"\x89PNG\r\n\x1a\n-fake-screenshot-image-bytes-"
        image_path.write_bytes(image_bytes)

        ui_analysis = (
            "A settings screen with a sidebar navigation and a form "
            "containing three toggle switches."
        )

        transport.queue_chat_response(
            _tool_call_answer(
                "vision_analyze_ui",
                {"path": str(image_path)},
            )
        )
        transport.queue_chat_response(_text_answer(ui_analysis))
        transport.queue_chat_response(_text_answer(ui_analysis))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Review this screenshot: {image_path}")

        assert result.succeeded

        _, ui_call, _ = transport.chat_payloads
        assert ui_call["model"] == "minicpm-v4.5:latest"

        assert result.chat_response is not None
        assert "sidebar navigation" in result.chat_response.message.content


class TestVisionAnalyzeSceneEndToEnd:
    def test_analyze_scene_via_native_tool_calling(
        self, runtime, transport: _VisionScriptedOllamaTransport, tmp_path
    ) -> None:
        image_path = tmp_path / "beach.png"
        image_bytes = b"\x89PNG\r\n\x1a\n-fake-beach-image-bytes-"
        image_path.write_bytes(image_bytes)

        scene_analysis = "An outdoor beach scene at sunset, with calm waves."

        transport.queue_chat_response(
            _tool_call_answer(
                "vision_analyze_scene",
                {"path": str(image_path)},
            )
        )
        transport.queue_chat_response(_text_answer(scene_analysis))
        transport.queue_chat_response(_text_answer(scene_analysis))

        session = InterfaceSession(runtime, system_prompt=None)
        result = session.submit_text(f"Is this indoor or outdoor? {image_path}")

        assert result.succeeded

        _, scene_call, _ = transport.chat_payloads
        assert scene_call["model"] == "minicpm-v4.5:latest"

        assert result.chat_response is not None
        assert "outdoor beach scene" in result.chat_response.message.content
