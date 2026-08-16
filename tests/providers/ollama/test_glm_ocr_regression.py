"""
End-to-end regression test for the `glm-ocr` misclassification bug.

Exercises the full, real pipeline - Provider Discovery
(`build_provider_model()`) -> Mechanical Provider Metadata
(`model_mapping.py`) -> Semantic Enrichment (`parika.core.semantics`)
-> `ProviderModel` -> Planner's (unchanged) filtering/ranking
(`build_execution_requirements()` -> `select_provider_model()`) - and
demonstrates the exact scenario the architecture brief requires:

    "hello"                          -> glm-ocr is filtered out
    "Extract text from this invoice" -> glm-ocr is selected

Task Classification itself (turning message text into a
`CapabilityCategory`) happens upstream, in the Interfaces layer/AI
Context Engineering, before `Brain.handle()` is ever called (see
`task_classification.py`'s module docstring) - Planner never re-parses
message text. This test therefore drives the two scenarios the same
way Planner itself is driven: via the resolved `CapabilityCategory`
("hello" resolves to an ordinary `LLM`/general-chat capability;
"Extract text from this invoice" resolves to the `OCR` capability),
proving the fix at every layer that is actually this change's
responsibility.
"""

from __future__ import annotations

import logging

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.planner.model_selection.config import ModelSelectionConfig
from parika.core.planner.model_selection.preference_rules import (
    DEFAULT_PREFERENCE_RULES,
)
from parika.core.planner.model_selection.requirements import (
    build_execution_requirements,
)
from parika.core.planner.model_selection.rules import DEFAULT_WEIGHTED_RULES
from parika.core.planner.model_selection.selector import select_provider_model
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.providers.ollama.discovery import build_provider_model

_LOGGER = logging.getLogger("test.glm_ocr_regression")
_RULES = (*DEFAULT_WEIGHTED_RULES, *DEFAULT_PREFERENCE_RULES)


def _discovered_glm_ocr() -> object:
    """
    Build the `ProviderModel` PARIKA actually discovers for `glm-ocr`,
    using the real Ollama discovery pipeline against a realistic
    `/api/show` payload (`capabilities: ["completion", "vision"]`).
    """

    return build_provider_model(
        "glm-ocr:latest",
        tags_entry={"details": {"family": "glm4", "parameter_size": "9B"}},
        show_payload={
            "capabilities": ["completion", "vision"],
            "model_info": {"glm4.context_length": 8192},
        },
    )


def _discovered_general_chat_model() -> object:
    """
    An ordinary, unspecialized chat model, discovered the same way,
    with no Local Curated Override registered for it.
    """

    return build_provider_model(
        "qwen3-coder-next:latest",
        tags_entry={"details": {"family": "qwen3", "parameter_size": "30B"}},
        show_payload={
            "capabilities": ["completion", "tools"],
            "model_info": {"qwen3.context_length": 40960},
        },
    )


def _provider(*models) -> Provider:
    return Provider(
        id="provider.ollama",
        name="Ollama",
        health=ProviderHealth(available=True),
        models=tuple(models),
    )


class TestHelloNeverSelectsGlmOcr:
    def test_glm_ocr_is_filtered_out_for_ordinary_conversation(self) -> None:
        glm_ocr = _discovered_glm_ocr()
        chat_model = _discovered_general_chat_model()

        # glm-ocr must no longer advertise "general_chat".
        assert "general_chat" not in glm_ocr.specializations
        assert glm_ocr.specializations == {"ocr", "document_understanding"}

        provider = _provider(glm_ocr, chat_model)

        # "hello" resolves, upstream, to an ordinary LLM/general-chat
        # capability request.
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.LLM,
            goal_metadata={},
        )

        result = select_provider_model(
            providers=[provider],
            requirements=requirements,
            config=ModelSelectionConfig(),
            rules=_RULES,
            logger=_LOGGER,
        )

        assert result.succeeded
        assert result.selected_model.id == "qwen3-coder-next:latest"

        by_id = {
            evaluation.model_id: evaluation
            for evaluation in result.evaluated_candidates
        }
        assert by_id["glm-ocr:latest"].accepted is False


class TestInvoiceExtractionSelectsGlmOcr:
    def test_glm_ocr_is_selected_for_ocr_task(self) -> None:
        glm_ocr = _discovered_glm_ocr()
        chat_model = _discovered_general_chat_model()

        provider = _provider(glm_ocr, chat_model)

        # "Extract text from this invoice" resolves, upstream, to the
        # OCR capability.
        requirements = build_execution_requirements(
            capability=ModelCapability.TEXT_GENERATION,
            category=CapabilityCategory.OCR,
            goal_metadata={},
        )

        result = select_provider_model(
            providers=[provider],
            requirements=requirements,
            config=ModelSelectionConfig(),
            rules=_RULES,
            logger=_LOGGER,
        )

        assert result.succeeded
        assert result.selected_model.id == "glm-ocr:latest"

        by_id = {
            evaluation.model_id: evaluation
            for evaluation in result.evaluated_candidates
        }
        assert by_id["qwen3-coder-next:latest"].accepted is False
