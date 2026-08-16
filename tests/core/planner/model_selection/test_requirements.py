"""
Unit tests for `parika.core.planner.model_selection.requirements`.
"""

from __future__ import annotations

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.planner.model_selection.requirements import (
    CapabilityHint,
    ExecutionRequirements,
    InformationFreshness,
    ReasoningLevel,
    Requirement,
    build_execution_requirements,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)


class TestBuildExecutionRequirementsDefaults:
    def test_defaults_to_normal_reasoning_for_llm_category(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={},
        )

        assert requirements.capability is ModelCapability.TEXT_GENERATION
        assert requirements.reasoning_level is ReasoningLevel.NORMAL
        assert requirements.tool_calling is Requirement.NOT_NEEDED

    def test_defaults_to_complex_reasoning_for_reasoning_category(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.REASONING,
            category=CapabilityCategory.REASONING,
            goal_metadata={},
        )

        assert requirements.reasoning_level is ReasoningLevel.COMPLEX

    def test_defaults_to_complex_reasoning_for_planning_category(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.PLANNING,
            goal_metadata={},
        )

        assert requirements.reasoning_level is ReasoningLevel.COMPLEX


class TestBuildExecutionRequirementsOverrides:
    def test_instance_override_is_used_as_is(self) -> None:
        override = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
            reasoning_level=ReasoningLevel.SIMPLE,
        )

        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={"execution_requirements": override},
        )

        assert requirements is override

    def test_dict_override_coerces_string_enum_values(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {
                    "reasoning_level": "complex",
                    "tool_calling": "required",
                }
            },
        )

        assert requirements.reasoning_level is ReasoningLevel.COMPLEX
        assert requirements.tool_calling is Requirement.REQUIRED

    def test_dict_override_supports_plain_fields(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {
                    "streaming_required": True,
                    "min_context_window": 8192,
                }
            },
        )

        assert requirements.streaming_required is True
        assert requirements.min_context_window == 8192

    def test_dict_override_ignores_unknown_keys(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {"nonexistent_field": "x"}
            },
        )

        assert requirements.capability is ModelCapability.TEXT_GENERATION

    def test_dict_override_cannot_change_capability(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {"capability": "embedding"}
            },
        )

        assert requirements.capability is ModelCapability.TEXT_GENERATION

    def test_no_override_present_returns_defaults(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={"unrelated": "value"},
        )

        assert requirements.reasoning_level is ReasoningLevel.NORMAL


class TestExecutionRequirementsImmutability:
    def test_metadata_defaults_to_empty_mapping(self) -> None:
        requirements = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION
        )

        assert dict(requirements.metadata) == {}

    def test_capability_hints_defaults_to_empty_frozenset(self) -> None:
        requirements = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION
        )

        assert requirements.capability_hints == frozenset()

    def test_new_task_classification_fields_default_empty(self) -> None:
        requirements = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION
        )

        assert requirements.task_category == ""
        assert requirements.required_specializations == frozenset()
        assert requirements.required_capabilities == frozenset()
        assert requirements.required_modalities == frozenset()
        assert requirements.required_execution_features == frozenset()
        assert requirements.available_resources is None

    def test_frozenset_fields_are_coerced_from_plain_iterables(self) -> None:
        requirements = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
            required_specializations=["general_chat", "general_chat"],
            required_modalities=("text",),
        )

        assert requirements.required_specializations == frozenset(
            {"general_chat"}
        )
        assert requirements.required_modalities == frozenset({"text"})


class TestBuildExecutionRequirementsTaskClassification:
    """
    `build_execution_requirements()` derives Task Classification's
    `required_specializations`/`required_capabilities`/
    `required_modalities`/`required_execution_features` from the
    resolved Capability category by default, and lets an explicit
    override replace any of them.
    """

    def test_llm_category_defaults_to_general_chat_specialization(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={},
        )

        assert requirements.task_category == "general_chat"
        assert requirements.required_specializations == frozenset(
            {"general_chat"}
        )

    def test_vision_category_defaults_to_vision_understanding(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.VISION,
            category=CapabilityCategory.VISION,
            goal_metadata={},
        )

        assert requirements.task_category == "vision_understanding"
        assert requirements.required_specializations == frozenset(
            {"vision_understanding"}
        )
        assert requirements.required_capabilities == frozenset(
            {ModelCapability.VISION}
        )
        assert requirements.required_modalities == frozenset({"image"})

    def test_ocr_category_defaults_to_ocr_specialization(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.VISION,
            category=CapabilityCategory.OCR,
            goal_metadata={},
        )

        assert requirements.task_category == "ocr"
        assert requirements.required_specializations == frozenset({"ocr"})

    def test_category_with_no_task_classification_default_stays_empty(
        self,
    ) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.CUSTOM,
            goal_metadata={},
        )

        assert requirements.task_category == ""
        assert requirements.required_specializations == frozenset()

    def test_explicit_task_category_override_replaces_default(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {"task_category": "coding"}
            },
        )

        assert requirements.task_category == "coding"
        assert requirements.required_specializations == frozenset({"coding"})
        assert requirements.required_capabilities == frozenset(
            {ModelCapability.CODING}
        )

    def test_unrecognized_task_category_override_gets_generic_profile(
        self,
    ) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {
                    "task_category": "video_editing",
                }
            },
        )

        assert requirements.task_category == "video_editing"
        assert requirements.required_specializations == frozenset(
            {"video_editing"}
        )

    def test_explicit_required_specializations_override_wins(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {
                    "required_specializations": ["custom_tag"],
                }
            },
        )

        assert requirements.required_specializations == frozenset(
            {"custom_tag"}
        )

    def test_explicit_required_execution_features_override_coerces_enum(
        self,
    ) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {
                    "required_execution_features": ["tool_calling"],
                }
            },
        )

        assert requirements.required_execution_features == frozenset(
            {ModelExecutionFeature.TOOL_CALLING}
        )

    def test_available_resources_is_threaded_through(self) -> None:
        sentinel = object()

        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={},
            available_resources=sentinel,  # type: ignore[arg-type]
        )

        assert requirements.available_resources is sentinel


class TestBuildExecutionRequirementsOverride:
    """
    `build_execution_requirements()` precedence: an explicit
    `Goal.metadata["execution_requirements"]` override always wins;
    otherwise the resolved Capability category's neutral default
    applies. Planner's former Requirement Inference framework (which
    used to derive `tool_calling`/`information_freshness`/
    `capability_hints` from `goal_inputs["message"]` via pattern/regex
    rules) has been removed -- see `docs/architecture/
    Request_Understanding.md` -- so `goal_inputs["message"]` is no
    longer read for inference at all; callers now supply requirements
    explicitly.
    """

    def test_no_override_produces_neutral_category_default(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            capability_id="chat.respond",
            goal_metadata={},
            goal_inputs={},
        )

        assert requirements.tool_calling is Requirement.NOT_NEEDED
        assert requirements.information_freshness is InformationFreshness.STATIC
        assert requirements.capability_hints == frozenset()

    def test_message_in_goal_inputs_is_never_read_for_inference(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            capability_id="chat.respond",
            goal_metadata={},
            goal_inputs={"message": "What is the current time in IST?"},
        )

        assert requirements.tool_calling is Requirement.NOT_NEEDED
        assert requirements.information_freshness is InformationFreshness.STATIC
        assert requirements.capability_hints == frozenset()

    def test_explicit_dict_override_sets_tool_calling(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            capability_id="chat.respond",
            goal_metadata={
                "execution_requirements": {"tool_calling": "preferred"}
            },
            goal_inputs={},
        )

        assert requirements.tool_calling is Requirement.PREFERRED

    def test_explicit_partial_override_keeps_other_fields_at_default(self) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            capability_id="chat.respond",
            goal_metadata={
                "execution_requirements": {"streaming_required": True}
            },
            goal_inputs={},
        )

        assert requirements.streaming_required is True
        assert requirements.tool_calling is Requirement.NOT_NEEDED

    def test_full_instance_override_is_used_as_is(self) -> None:
        override = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
            tool_calling=Requirement.REQUIRED,
        )

        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            capability_id="chat.respond",
            goal_metadata={"execution_requirements": override},
            goal_inputs={},
        )

        assert requirements is override
