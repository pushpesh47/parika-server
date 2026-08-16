"""
Unit tests for `parika.core.planner.model_selection.task_classification`.
"""

from __future__ import annotations

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.planner.model_selection.task_classification import (
    TaskCategory,
    TaskRequirementProfile,
    default_task_category_for,
    get_task_profile,
    register_task_profile,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)


class TestDefaultTaskCategoryFor:
    def test_llm_maps_to_general_chat(self) -> None:
        assert default_task_category_for(CapabilityCategory.LLM) is (
            TaskCategory.GENERAL_CHAT
        )

    def test_vision_maps_to_vision_understanding(self) -> None:
        assert default_task_category_for(CapabilityCategory.VISION) is (
            TaskCategory.VISION_UNDERSTANDING
        )

    def test_ocr_maps_to_ocr(self) -> None:
        assert default_task_category_for(CapabilityCategory.OCR) is (
            TaskCategory.OCR
        )

    def test_unmapped_category_returns_none(self) -> None:
        assert default_task_category_for(CapabilityCategory.CUSTOM) is None


class TestGetTaskProfileBuiltins:
    def test_general_chat_requires_general_chat_specialization(self) -> None:
        profile = get_task_profile(TaskCategory.GENERAL_CHAT)

        assert profile.required_specializations == frozenset({"general_chat"})

    def test_ocr_requires_ocr_specialization_and_image_modality(self) -> None:
        profile = get_task_profile(TaskCategory.OCR)

        assert profile.required_specializations == frozenset({"ocr"})
        assert profile.required_modalities == frozenset({"image"})

    def test_coding_requires_coding_capability(self) -> None:
        profile = get_task_profile(TaskCategory.CODING)

        assert profile.required_capabilities == frozenset(
            {ModelCapability.CODING}
        )

    def test_tool_use_requires_tool_calling_execution_feature(self) -> None:
        profile = get_task_profile(TaskCategory.TOOL_USE)

        assert profile.required_execution_features == frozenset(
            {ModelExecutionFeature.TOOL_CALLING}
        )

    def test_image_generation_requires_image_generation_capability(
        self,
    ) -> None:
        profile = get_task_profile(TaskCategory.IMAGE_GENERATION)

        assert profile.required_capabilities == frozenset(
            {ModelCapability.IMAGE_GENERATION}
        )

    def test_speech_to_text_requires_audio_modality(self) -> None:
        profile = get_task_profile(TaskCategory.SPEECH_TO_TEXT)

        assert profile.required_modalities == frozenset({"audio"})

    def test_accepts_plain_string_equal_to_enum_value(self) -> None:
        profile = get_task_profile("general_chat")

        assert profile.required_specializations == frozenset({"general_chat"})


class TestGetTaskProfileFallback:
    """
    A task category with no registered or built-in profile still gets
    a sensible, generic profile - no code change required anywhere to
    support a brand new future task category.
    """

    def test_unknown_task_category_requires_specialization_matching_itself(
        self,
    ) -> None:
        profile = get_task_profile("legal_document_analysis")

        assert profile.required_specializations == frozenset(
            {"legal_document_analysis"}
        )
        assert profile.required_capabilities == frozenset()
        assert profile.required_modalities == frozenset()

    def test_empty_string_task_category_requires_nothing(self) -> None:
        profile = get_task_profile("")

        assert profile.required_specializations == frozenset()


class TestRegisterTaskProfile:
    def test_registered_profile_overrides_builtin(self) -> None:
        register_task_profile(
            TaskRequirementProfile(
                task_category=TaskCategory.GENERAL_CHAT,
                required_specializations=frozenset({"custom_chat_tag"}),
            )
        )

        try:
            profile = get_task_profile(TaskCategory.GENERAL_CHAT)

            assert profile.required_specializations == frozenset(
                {"custom_chat_tag"}
            )
        finally:
            # Restore the built-in profile so this test does not leak
            # state into other tests in the same process.
            register_task_profile(
                TaskRequirementProfile(
                    task_category=TaskCategory.GENERAL_CHAT,
                    required_specializations=frozenset({"general_chat"}),
                )
            )

    def test_registering_a_brand_new_task_category_requires_no_code_change(
        self,
    ) -> None:
        register_task_profile(
            TaskRequirementProfile(
                task_category="video_editing",
                required_specializations=frozenset({"video_editing"}),
                required_modalities=frozenset({"video"}),
            )
        )

        profile = get_task_profile("video_editing")

        assert profile.required_specializations == frozenset(
            {"video_editing"}
        )
        assert profile.required_modalities == frozenset({"video"})
