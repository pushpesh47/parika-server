"""
Unit tests for `parika.interfaces.formatting.response_formatter`.
"""

from __future__ import annotations

from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_result import ChatResult, ToolInvocation
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.interfaces.formatting.response_formatter import format_chat_turn
from parika.interfaces.session import ChatTurnResult


def _successful_result(chat_response: ChatResult) -> ChatTurnResult:
    goal_result = GoalResult(
        goal_id="g1",
        task_id="t1",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": chat_response}),
    )
    brain_response = BrainResponse(
        request_id="r1", plan_id="p1", results=(goal_result,)
    )

    return ChatTurnResult(brain_response=brain_response)


def _failed_result(message: str) -> ChatTurnResult:
    brain_response = BrainResponse(
        request_id="r1",
        plan_id=None,
        results=(),
        planning_failure=RuntimeError(message),
    )

    return ChatTurnResult(brain_response=brain_response)


class TestFormatChatTurn:
    def test_formats_plain_answer(self) -> None:
        chat_response = ChatResult(
            message=ChatMessage(role="assistant", content="Hello!")
        )

        text = format_chat_turn(_successful_result(chat_response))

        assert text == "Hello!"

    def test_lists_tool_invocations_before_answer(self) -> None:
        invocation = ToolInvocation(
            name="web_search",
            capability_id="web.search",
            succeeded=True,
            content="{}",
        )
        chat_response = ChatResult(
            message=ChatMessage(role="assistant", content="Found it."),
            tool_invocations=(invocation,),
        )

        text = format_chat_turn(_successful_result(chat_response))

        lines = text.split("\n")
        assert lines[0] == "[used tool `web_search` - ok]"
        assert lines[-1] == "Found it."

    def test_marks_failed_tool_invocation(self) -> None:
        invocation = ToolInvocation(
            name="web_search",
            capability_id="web.search",
            succeeded=False,
            content="{}",
        )
        chat_response = ChatResult(
            message=ChatMessage(role="assistant", content="Sorry."),
            tool_invocations=(invocation,),
        )

        text = format_chat_turn(_successful_result(chat_response))

        assert "failed" in text.split("\n")[0]

    def test_formats_error_for_failed_turn(self) -> None:
        text = format_chat_turn(_failed_result("no provider available"))

        assert text == "Error: no provider available"
