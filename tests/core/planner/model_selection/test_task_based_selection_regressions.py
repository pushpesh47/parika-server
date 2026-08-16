"""
Model Selection Framework - Task-Based Selection Regression Tests.

These tests exercise the full pipeline (`build_execution_requirements()`
-> `select_provider_model()`, i.e. Task Classification -> filtering ->
ranking) end-to-end against multi-candidate pools where an earlier,
capability-only selection strategy would have picked the wrong model -
the exact failure modes described in the Model Selection Framework's
design brief:

    - An OCR model competing for, and winning, an ordinary conversation.
    - A coding-specialized model being ignored for a coding task.
    - A vision-specialized model being ignored for vision understanding.
    - An image-generation model being ignored for image generation.
    - A speech model being ignored for a speech task.
    - A general-purpose chat model losing to an irrelevant specialist.
    - A reasoning-capable model not being favored for complex reasoning.
    - A tool-capable model not being favored when tool execution is
      required.

Every candidate here is a plain, synthetic `ProviderModel` -- nothing
in this module, `task_classification.py`, `filtering.py`, or
`selector.py` ever names a real model or provider. That is itself part
of what these tests verify: the framework's provider/model
independence.
"""

from __future__ import annotations

import logging

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.planner.model_selection.config import ModelSelectionConfig
from parika.core.planner.model_selection.requirements import (
    Requirement,
    build_execution_requirements,
)
from parika.core.planner.model_selection.rules import DEFAULT_WEIGHTED_RULES
from parika.core.planner.model_selection.preference_rules import (
    DEFAULT_PREFERENCE_RULES,
)
from parika.core.planner.model_selection.selector import select_provider_model
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel

_LOGGER = logging.getLogger("test.model_selection.task_based_regressions")
_RULES = (*DEFAULT_WEIGHTED_RULES, *DEFAULT_PREFERENCE_RULES)


def _select(*, provider: Provider, requirements):
    return select_provider_model(
        providers=[provider],
        requirements=requirements,
        config=ModelSelectionConfig(),
        rules=_RULES,
        logger=_LOGGER,
    )


def _healthy_provider(*models: ProviderModel) -> Provider:
    return Provider(
        id="provider.mixed",
        name="Mixed Fleet",
        health=ProviderHealth(available=True),
        models=tuple(models),  # type: ignore[arg-type]
    )


def _general_chat_model(model_id: str = "chat-model") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        execution_features=frozenset({ModelExecutionFeature.STREAMING}),
        specializations=frozenset({"general_chat"}),
        supported_modalities=frozenset({"text"}),
    )


def _ocr_model(model_id: str = "ocr-model") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.VISION}
        ),
        specializations=frozenset({"ocr"}),
        supported_modalities=frozenset({"text", "image"}),
    )


def _coding_model(model_id: str = "coding-model") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.CODING}
        ),
        specializations=frozenset({"coding"}),
        supported_modalities=frozenset({"text"}),
    )


def _vision_model(model_id: str = "vision-model") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.VISION}
        ),
        specializations=frozenset({"vision_understanding"}),
        supported_modalities=frozenset({"text", "image"}),
    )


def _image_generation_model(model_id: str = "image-gen-model") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset({ModelCapability.IMAGE_GENERATION}),
        specializations=frozenset({"image_generation"}),
        supported_modalities=frozenset({"image"}),
    )


def _speech_to_text_model(model_id: str = "speech-model") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset({ModelCapability.SPEECH_TO_TEXT}),
        specializations=frozenset({"speech_to_text"}),
        supported_modalities=frozenset({"audio"}),
    )


def _reasoning_model(model_id: str = "reasoning-model") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset(
            {ModelCapability.TEXT_GENERATION, ModelCapability.REASONING}
        ),
        specializations=frozenset({"reasoning"}),
        supported_modalities=frozenset({"text"}),
    )


def _tool_capable_model(model_id: str = "tool-model") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        execution_features=frozenset({ModelExecutionFeature.TOOL_CALLING}),
        specializations=frozenset({"general_chat", "tool_use"}),
        supported_modalities=frozenset({"text"}),
    )


class TestOcrNeverSelectedForConversation:
    def test_ocr_model_is_excluded_from_general_chat(self) -> None:
        provider = _healthy_provider(
            _ocr_model(), _general_chat_model(), _coding_model()
        )
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={},
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "chat-model"

        by_id = {
            evaluation.model_id: evaluation
            for evaluation in result.evaluated_candidates
        }
        assert by_id["ocr-model"].accepted is False

    def test_ocr_only_pool_still_fails_general_chat(self) -> None:
        provider = _healthy_provider(_ocr_model())
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={},
        )

        result = _select(provider=provider, requirements=requirements)

        assert not result.succeeded


class TestCodingModelsPreferredForCoding:
    def test_coding_model_wins_over_general_chat_model_for_coding_task(
        self,
    ) -> None:
        provider = _healthy_provider(_general_chat_model(), _coding_model())
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {"task_category": "coding"}
            },
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "coding-model"


class TestVisionModelsPreferredForVisionUnderstanding:
    def test_vision_model_wins_and_others_are_excluded(self) -> None:
        provider = _healthy_provider(
            _general_chat_model(), _vision_model(), _ocr_model()
        )
        requirements = build_execution_requirements(
            capability=ModelCapability.VISION,
            category=CapabilityCategory.VISION,
            goal_metadata={},
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "vision-model"


class TestImageGenerationModelsPreferredForImageGeneration:
    def test_image_generation_model_is_the_only_viable_candidate(self) -> None:
        provider = _healthy_provider(
            _general_chat_model(), _image_generation_model()
        )
        requirements = build_execution_requirements(
            capability=ModelCapability.IMAGE_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {
                    "task_category": "image_generation",
                }
            },
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "image-gen-model"


class TestSpeechModelsPreferredForSpeechTasks:
    def test_speech_model_is_selected_for_speech_to_text(self) -> None:
        provider = _healthy_provider(
            _general_chat_model(), _speech_to_text_model()
        )
        requirements = build_execution_requirements(
            capability=ModelCapability.SPEECH_TO_TEXT,
            category=CapabilityCategory.SPEECH,
            goal_metadata={},
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "speech-model"


class TestGeneralChatModelsPreferredForConversation:
    def test_general_chat_model_beats_every_specialist(self) -> None:
        provider = _healthy_provider(
            _ocr_model(),
            _coding_model(),
            _vision_model(),
            _general_chat_model(),
        )
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={},
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "chat-model"


class TestReasoningModelsPreferredForComplexReasoning:
    def test_reasoning_model_wins_for_complex_reasoning(self) -> None:
        provider = _healthy_provider(
            _general_chat_model(), _reasoning_model()
        )
        requirements = build_execution_requirements(
            capability=ModelCapability.REASONING,
            category=CapabilityCategory.REASONING,
            goal_metadata={},
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "reasoning-model"


class TestToolCapableModelsPreferredWhenToolExecutionRequired:
    def test_tool_capable_model_wins_when_tool_calling_is_required(
        self,
    ) -> None:
        provider = _healthy_provider(
            _general_chat_model(), _tool_capable_model()
        )
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {"tool_calling": "required"}
            },
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "tool-model"

    def test_tool_capable_model_is_ranked_ahead_when_only_preferred(
        self,
    ) -> None:
        provider = _healthy_provider(
            _general_chat_model(), _tool_capable_model()
        )
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {"tool_calling": "preferred"}
            },
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "tool-model"


class TestFutureProviderAndModelCompatibility:
    """
    A brand new task category (never registered anywhere, standing in
    for a future provider/modality PARIKA does not support yet) still
    participates correctly in filtering and ranking with zero code
    changes to `task_classification.py`, `filtering.py`, `selector.py`,
    or `planner.py` -- only an explicit `task_category` override and a
    Provider that advertises a matching `specializations` tag.
    """

    def test_novel_task_category_correctly_filters_unrelated_candidates(
        self,
    ) -> None:
        future_model = ProviderModel(
            id="future-model",
            name="future-model",
            capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
            specializations=frozenset({"legal_document_analysis"}),
            supported_modalities=frozenset({"text"}),
        )
        provider = _healthy_provider(_general_chat_model(), future_model)

        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={
                "execution_requirements": {
                    "task_category": "legal_document_analysis",
                }
            },
        )

        result = _select(provider=provider, requirements=requirements)

        assert result.succeeded
        assert result.selected_model.id == "future-model"


class TestProviderIndependence:
    """
    Nothing in the filtering/ranking pipeline ever branches on a
    provider id or model id - only on generic, provider-reported
    metadata. Registering the exact same models under a differently
    named, differently identified Provider produces an identical
    selection outcome.
    """

    def test_selection_outcome_is_independent_of_provider_identity(
        self,
    ) -> None:
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={},
        )

        provider_a = Provider(
            id="provider.alpha",
            name="Alpha",
            health=ProviderHealth(available=True),
            models=(_ocr_model(), _general_chat_model()),  # type: ignore[arg-type]
        )
        provider_b = Provider(
            id="provider.beta-completely-different-name",
            name="A Totally Different Vendor",
            health=ProviderHealth(available=True),
            models=(_ocr_model(), _general_chat_model()),  # type: ignore[arg-type]
        )

        result_a = _select(provider=provider_a, requirements=requirements)
        result_b = _select(provider=provider_b, requirements=requirements)

        assert result_a.succeeded and result_b.succeeded
        assert result_a.selected_model.id == result_b.selected_model.id
