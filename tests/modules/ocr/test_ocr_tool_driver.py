"""
Unit tests for OcrToolDriver, using a fake Brain -- never a real
Provider or a real filesystem. Mirrors
`tests/modules/coding_agent/test_standard_agent.py`'s own fake-Brain
shape exactly.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.modules.ocr.config import OcrToolConfig
from parika.modules.ocr.driver import (
    DEFAULT_RECOGNITION_INSTRUCTION,
    FILESYSTEM_READ_CAPABILITY_ID,
    OcrToolDriver,
)
from parika.modules.ocr.exceptions import OcrImageReadError, OcrRecognitionError
from parika.modules.ocr.module_driver import PROVIDER_EXTRACT_TEXT_CAPABILITY_ID

_IMAGE_BASE64 = base64.b64encode(b"fake-image-bytes").decode("ascii")

_TEXT_LAYER_PDF = base64.b64encode(
    b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 58>>stream
BT /F1 24 Tf 20 100 Td (Hello PARIKA OCR) Tj ET
endstream
endobj
trailer
<</Size 6/Root 1 0 R>>
%%EOF"""
).decode("ascii")

_SCANNED_PDF = base64.b64encode(
    b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj
trailer
<</Size 4/Root 1 0 R>>
%%EOF"""
).decode("ascii")


def _real_image_base64(*, width: int = 100, height: int = 100, color=(10, 20, 30)) -> str:
    image = Image.new("RGB", (width, height), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class _FakeBrain:
    def __init__(self, responses: list[BrainResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[BrainRequest] = []

    def handle(self, request: BrainRequest) -> BrainResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def _filesystem_read_result(payload: dict) -> GoalResult:
    return GoalResult(
        goal_id="g1",
        task_id="task-1",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": ToolResponse(result=payload)}),
    )


def _failed_result(reason: str) -> GoalResult:
    return GoalResult(
        goal_id="g1",
        task_id="task-1",
        status=TaskStatus.FAILED,
        response=None,
        failure=RuntimeError(reason),
    )


def _recognition_result(text: str) -> GoalResult:
    return GoalResult(
        goal_id="g2",
        task_id="task-2",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(
            outputs={
                "result": ChatResult(
                    message=ChatMessage(role="assistant", content=text)
                )
            }
        ),
    )


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


class TestOcrToolDriverExecute:
    def test_reads_image_and_recognizes_text(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result(
                            {
                                "path": "/mnt/dev/test/p1.png",
                                "content_base64": _IMAGE_BASE64,
                                "encoding": "base64",
                                "size": 17,
                            }
                        ),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(
                        _recognition_result(
                            "Aadhaar Number: 1234 5678 9012\nName: Test User"
                        ),
                    ),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        response = driver.execute(
            _request(
                path="/mnt/dev/test/p1.png",
                instruction="Extract the Aadhaar Number and Name",
            )
        )

        assert response.result == {
            "text": "Aadhaar Number: 1234 5678 9012\nName: Test User"
        }
        assert response.attributes["path"] == "/mnt/dev/test/p1.png"

        assert len(fake_brain.requests) == 2

        read_goal = fake_brain.requests[0].goals[0]
        assert read_goal.capability_id == FILESYSTEM_READ_CAPABILITY_ID
        assert read_goal.inputs == {"path": "/mnt/dev/test/p1.png", "binary": True}
        assert read_goal.provider_request_builder is None

        recognize_goal = fake_brain.requests[1].goals[0]
        assert recognize_goal.capability_id == PROVIDER_EXTRACT_TEXT_CAPABILITY_ID
        assert recognize_goal.provider_request_builder is not None

        # The provider_request_builder closure -- exactly like
        # StandardCodingAgent._submit_decomposition_goal()'s -- is
        # never invoked by the driver itself; Planner invokes it once
        # a model is selected (`resolution`/`model` are irrelevant to
        # this closure, exactly like `goal_builder.py`'s own).
        built_request = recognize_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert isinstance(built_request, ChatRequest)
        assert len(built_request.messages) == 1

        sent_message = built_request.messages[0]
        assert sent_message.role == "user"
        assert sent_message.content == "Extract the Aadhaar Number and Name"
        assert sent_message.images == (_IMAGE_BASE64,)

    def test_uses_default_instruction_when_omitted(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("some text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        driver.execute(_request(path="/mnt/dev/test/p1.png"))

        recognize_goal = fake_brain.requests[1].goals[0]
        built_request = recognize_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert built_request.messages[0].content == DEFAULT_RECOGNITION_INSTRUCTION

    def test_raises_when_path_is_missing(self) -> None:
        driver = OcrToolDriver(
            brain=_FakeBrain([]),  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        with pytest.raises(OcrImageReadError):
            driver.execute(_request())

    def test_raises_when_filesystem_read_fails(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(_failed_result("path not found"),),
                )
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        with pytest.raises(OcrImageReadError, match="path not found"):
            driver.execute(_request(path="/mnt/dev/test/missing.png"))

    def test_forwards_execution_requirements_into_inner_goal_metadata(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("some text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        execution_requirements = {"reasoning_level": "simple"}

        driver.execute(
            ToolRequest(
                arguments={"path": "/mnt/dev/test/p1.png"},
                metadata={"execution_requirements": execution_requirements},
            )
        )

        recognize_goal = fake_brain.requests[1].goals[0]
        assert (
            recognize_goal.metadata["execution_requirements"]
            == execution_requirements
        )

        read_goal = fake_brain.requests[0].goals[0]
        assert read_goal.metadata == {}

    def test_no_hint_leaves_inner_goal_metadata_empty(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("some text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        driver.execute(_request(path="/mnt/dev/test/p1.png"))

        recognize_goal = fake_brain.requests[1].goals[0]
        assert recognize_goal.metadata == {}

    def test_raises_when_recognition_fails(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_failed_result("no OCR-capable model available"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        with pytest.raises(OcrRecognitionError, match="no OCR-capable model"):
            driver.execute(_request(path="/mnt/dev/test/p1.png"))


class TestOcrToolDriverRegionAndLanguage:
    """
    Covers the two additive inputs `region` and `language` - purely
    optional; every test above (which never sets either) proves the
    default path is byte-for-byte unchanged.
    """

    def test_region_crops_before_recognition(self) -> None:
        image_base64 = _real_image_base64(width=200, height=200)
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": image_base64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("cropped text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        driver.execute(
            _request(
                path="/mnt/dev/test/p1.png",
                region={"x": 10, "y": 10, "width": 50, "height": 50},
            )
        )

        recognize_goal = fake_brain.requests[1].goals[0]
        built_request = recognize_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        sent_image = built_request.messages[0].images[0]

        cropped_bytes = base64.b64decode(sent_image)
        cropped_image = Image.open(io.BytesIO(cropped_bytes))
        assert cropped_image.size == (50, 50)
        # Never the same bytes as the original, uncropped image.
        assert sent_image != image_base64

    def test_malformed_region_falls_back_to_whole_image(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("some text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        driver.execute(_request(path="/mnt/dev/test/p1.png", region={"x": "bad"}))

        recognize_goal = fake_brain.requests[1].goals[0]
        built_request = recognize_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert built_request.messages[0].images == (_IMAGE_BASE64,)

    def test_language_hint_is_folded_into_the_instruction(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("some text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        driver.execute(_request(path="/mnt/dev/test/p1.png", language="Hindi"))

        recognize_goal = fake_brain.requests[1].goals[0]
        built_request = recognize_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert "Hindi" in built_request.messages[0].content


class TestOcrToolDriverOptInPreprocessing:
    def test_preprocess_true_sends_a_transformed_image(self) -> None:
        image_base64 = _real_image_base64(width=200, height=150, color=(180, 180, 180))
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": image_base64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("some text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        driver.execute(_request(path="/mnt/dev/test/p1.png", preprocess=True))

        recognize_goal = fake_brain.requests[1].goals[0]
        built_request = recognize_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        sent_image = built_request.messages[0].images[0]

        assert sent_image != image_base64

    def test_preprocess_omitted_leaves_the_default_path_unchanged(self) -> None:
        image_base64 = _real_image_base64()
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": image_base64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("some text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        driver.execute(_request(path="/mnt/dev/test/p1.png"))

        recognize_goal = fake_brain.requests[1].goals[0]
        built_request = recognize_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert built_request.messages[0].images[0] == image_base64


class TestOcrToolDriverPdfAwareness:
    def test_text_layer_page_is_never_recognized(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _TEXT_LAYER_PDF}),
                    ),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
            # "Hello PARIKA OCR" is 16 characters - shorter than the
            # config default (20); a lower threshold here matches
            # exactly what `test_pdf_support.py` already exercises
            # directly (`min_text_layer_chars=5`).
            config=OcrToolConfig(pdf_min_text_layer_chars=5),
        )

        response = driver.execute(_request(path="/mnt/dev/test/doc.pdf"))

        assert "Hello PARIKA OCR" in response.result["text"]
        assert response.result["pages"] == [
            {"page": 1, "text": "Hello PARIKA OCR", "source": "text_layer"}
        ]
        # Only the filesystem read - zero recognize calls for a page
        # that already has a usable text layer.
        assert len(fake_brain.requests) == 1

    def test_scanned_page_is_recognized_exactly_once(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _SCANNED_PDF}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("scanned page text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        response = driver.execute(_request(path="/mnt/dev/test/scan.pdf"))

        assert response.result["text"] == "scanned page text"
        assert response.result["pages"][0]["source"] == "ocr"
        assert response.result["pages"][0]["page"] == 1
        assert len(fake_brain.requests) == 2

    def test_non_pdf_bytes_take_the_ordinary_image_path(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_recognition_result("ordinary image text"),),
                ),
            ]
        )

        driver = OcrToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        )

        response = driver.execute(_request(path="/mnt/dev/test/p1.png"))

        assert response.result == {"text": "ordinary image text"}
