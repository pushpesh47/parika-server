"""Unit tests for TokenBudget and load_context_engine_config()."""

from __future__ import annotations

from parika.core.brain.context_engine.budget import (
    TokenBudget,
    load_context_engine_config,
)
from parika.core.configuration.configuration import Configuration


class TestTokenBudget:
    def test_usable_tokens_subtracts_reservation(self) -> None:
        budget = TokenBudget(
            max_context_tokens=1000,
            reserved_for_response=200,
            safety_reserve_tokens=0,
        )

        assert budget.usable_tokens == 800

    def test_usable_tokens_subtracts_safety_reserve_too(self) -> None:
        budget = TokenBudget(
            max_context_tokens=1000,
            reserved_for_response=200,
            safety_reserve_tokens=100,
        )

        assert budget.usable_tokens == 700

    def test_usable_tokens_never_negative(self) -> None:
        budget = TokenBudget(max_context_tokens=100, reserved_for_response=500)

        assert budget.usable_tokens == 0

    def test_warning_threshold(self) -> None:
        budget = TokenBudget(max_context_tokens=1000, warning_threshold=0.8)

        assert budget.is_over_warning_threshold(799) is False
        assert budget.is_over_warning_threshold(800) is True

    def test_defaults(self) -> None:
        budget = TokenBudget()

        assert budget.max_context_tokens == 8192
        assert budget.reserved_for_response == 1024
        assert budget.safety_reserve_tokens == 256

    def test_no_fixed_count_prompt_limits_remain(self) -> None:
        # Phase A.5: TokenBudget must never define a fixed entry/turn
        # count -- only token-denominated inputs PARIKA genuinely
        # owns and that cannot be derived from a selected model.
        for removed_field in (
            "recent_turns_kept",
            "max_memories",
            "max_knowledge_entries",
            "max_conversation_messages",
        ):
            assert not hasattr(TokenBudget(), removed_field)


class TestLoadContextEngineConfig:
    def test_none_configuration_returns_defaults(self) -> None:
        budget = load_context_engine_config(None)

        assert budget == TokenBudget()

    def test_reads_from_configuration(self) -> None:
        configuration = Configuration()
        configuration.load()

        budget = load_context_engine_config(configuration)

        # config/defaults.toml already defines these values explicitly.
        assert budget.max_context_tokens == 8192
        assert budget.safety_reserve_tokens == 256
