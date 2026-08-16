"""
Unit tests for `ToolCallResolver`'s extraction of the reserved
`model_selection_hint` tool-call argument
(`parika.providers.ollama.tool_calling`).
"""

from __future__ import annotations

from parika.core.brain.brain_request import BrainRequest
from parika.core.configuration.configuration import Configuration
from parika.core.logger.logger import Logger
from parika.core.planner.goal import Goal
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.brain.goal_result import GoalResult
from parika.providers.ollama.messages import OllamaToolCall, OllamaToolSpec
from parika.providers.ollama.tool_calling import (
    MODEL_SELECTION_HINT_ARGUMENT,
    ToolCallResolver,
    _extract_execution_requirements_override,
)

SPEC = OllamaToolSpec(
    name="vision_describe_image",
    description="Describe an image.",
    capability_id="vision.describe_image",
    parameters={"type": "object", "properties": {}},
)

TOOLS_BY_NAME = {SPEC.name: SPEC}


class _BrainResponse:
    def __init__(self, results, planning_failure=None) -> None:
        self.results = results
        self.planning_failure = planning_failure


class _RecordingBrain:
    """
    Minimal `Brain` double that records every submitted `Goal` and
    always reports success, so tests can assert exactly what
    `ToolCallResolver` built without exercising real planning/
    execution.
    """

    def __init__(self) -> None:
        self.received_goals: list[Goal] = []

    def handle(self, request: BrainRequest) -> _BrainResponse:
        goal = request.goals[0]
        self.received_goals.append(goal)

        return _BrainResponse(
            results=[
                GoalResult(
                    goal_id=goal.id,
                    task_id="task-1",
                    status=TaskStatus.COMPLETED,
                    response=TaskResponse(outputs={"result": "ok"}),
                )
            ]
        )


class TestExtractExecutionRequirementsOverride:
    def test_returns_none_when_hint_absent(self) -> None:
        arguments: dict[str, object] = {"path": "/tmp/a.png"}

        result = _extract_execution_requirements_override(arguments)

        assert result is None
        assert arguments == {"path": "/tmp/a.png"}

    def test_returns_none_when_hint_is_not_a_mapping(self) -> None:
        arguments: dict[str, object] = {
            MODEL_SELECTION_HINT_ARGUMENT: "not-a-dict"
        }

        result = _extract_execution_requirements_override(arguments)

        assert result is None
        assert MODEL_SELECTION_HINT_ARGUMENT not in arguments

    def test_pops_the_reserved_key_out_of_arguments(self) -> None:
        arguments: dict[str, object] = {
            "path": "/tmp/a.png",
            MODEL_SELECTION_HINT_ARGUMENT: {"reasoning_level": "simple"},
        }

        _extract_execution_requirements_override(arguments)

        assert arguments == {"path": "/tmp/a.png"}

    def test_extracts_candidate_models_under_metadata(self) -> None:
        arguments: dict[str, object] = {
            MODEL_SELECTION_HINT_ARGUMENT: {
                "candidate_models": [
                    {"provider_id": "provider.ollama", "model_id": "minicpm-v4.5", "confidence": 0.9}
                ]
            }
        }

        result = _extract_execution_requirements_override(arguments)

        assert result == {
            "metadata": {
                "candidate_models": [
                    {
                        "provider_id": "provider.ollama",
                        "model_id": "minicpm-v4.5",
                        "confidence": 0.9,
                    }
                ]
            }
        }

    def test_extracts_reasoning_level_as_a_top_level_override(self) -> None:
        arguments: dict[str, object] = {
            MODEL_SELECTION_HINT_ARGUMENT: {"reasoning_level": "complex"}
        }

        result = _extract_execution_requirements_override(arguments)

        assert result == {"reasoning_level": "complex"}

    def test_extracts_both_fields_together(self) -> None:
        arguments: dict[str, object] = {
            MODEL_SELECTION_HINT_ARGUMENT: {
                "reasoning_level": "simple",
                "candidate_models": [{"provider_id": "p", "model_id": "m"}],
            }
        }

        result = _extract_execution_requirements_override(arguments)

        assert result == {
            "reasoning_level": "simple",
            "metadata": {"candidate_models": [{"provider_id": "p", "model_id": "m"}]},
        }

    def test_ignores_unrecognized_fields(self) -> None:
        arguments: dict[str, object] = {
            MODEL_SELECTION_HINT_ARGUMENT: {"unknown_field": "whatever"}
        }

        result = _extract_execution_requirements_override(arguments)

        assert result is None

    def test_ignores_non_string_reasoning_level(self) -> None:
        arguments: dict[str, object] = {
            MODEL_SELECTION_HINT_ARGUMENT: {"reasoning_level": 42}
        }

        result = _extract_execution_requirements_override(arguments)

        assert result is None

    def test_ignores_non_list_candidate_models(self) -> None:
        arguments: dict[str, object] = {
            MODEL_SELECTION_HINT_ARGUMENT: {"candidate_models": "not-a-list"}
        }

        result = _extract_execution_requirements_override(arguments)

        assert result is None


class TestToolCallResolverForwardsExecutionRequirements:
    def test_goal_has_no_metadata_when_no_hint_supplied(self) -> None:
        brain = _RecordingBrain()
        resolver = ToolCallResolver(logger=Logger(Configuration()))
        resolver.bind_brain(brain)  # type: ignore[arg-type]

        resolver.resolve(
            OllamaToolCall(name="vision_describe_image", arguments={"path": "/tmp/a.png"}),
            TOOLS_BY_NAME,
        )

        assert len(brain.received_goals) == 1
        assert brain.received_goals[0].metadata == {}
        assert brain.received_goals[0].inputs == {"path": "/tmp/a.png"}

    def test_hint_flows_into_goal_metadata_and_is_removed_from_inputs(self) -> None:
        brain = _RecordingBrain()
        resolver = ToolCallResolver(logger=Logger(Configuration()))
        resolver.bind_brain(brain)  # type: ignore[arg-type]

        resolver.resolve(
            OllamaToolCall(
                name="vision_describe_image",
                arguments={
                    "path": "/tmp/a.png",
                    "model_selection_hint": {
                        "reasoning_level": "simple",
                        "candidate_models": [
                            {
                                "provider_id": "provider.ollama",
                                "model_id": "minicpm-v4.5",
                                "confidence": 0.9,
                            }
                        ],
                    },
                },
            ),
            TOOLS_BY_NAME,
        )

        goal = brain.received_goals[0]
        assert goal.inputs == {"path": "/tmp/a.png"}
        assert "model_selection_hint" not in goal.inputs
        assert goal.metadata["execution_requirements"]["reasoning_level"] == "simple"
        assert goal.metadata["execution_requirements"]["metadata"]["candidate_models"] == [
            {
                "provider_id": "provider.ollama",
                "model_id": "minicpm-v4.5",
                "confidence": 0.9,
            }
        ]

    def test_malformed_hint_does_not_break_resolution(self) -> None:
        brain = _RecordingBrain()
        resolver = ToolCallResolver(logger=Logger(Configuration()))
        resolver.bind_brain(brain)  # type: ignore[arg-type]

        content, capability_id, succeeded = resolver.resolve(
            OllamaToolCall(
                name="vision_describe_image",
                arguments={"path": "/tmp/a.png", "model_selection_hint": "garbage"},
            ),
            TOOLS_BY_NAME,
        )

        assert succeeded is True
        assert capability_id == "vision.describe_image"
        assert brain.received_goals[0].metadata == {}
