"""
Tests for Agent Profile
"""

from __future__ import annotations

import pytest

from parika.core.agent_orchestrator.agent_profile import AgentProfile
from parika.core.agent_orchestrator.agent_specialization import AgentSpecialization
from parika.core.capability_registry.capability_category import CapabilityCategory


class TestAgentProfile:
    def test_create_basic_profile(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.GENERAL,
        )
        assert profile.id == "test.agent"
        assert profile.name == "Test Agent"
        assert profile.specialization == AgentSpecialization.GENERAL

    def test_can_use_capability_with_allowed(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.CODING,
            allowed_capabilities=frozenset({"coding.execute_task"}),
        )
        assert profile.can_use_capability("coding.execute_task", CapabilityCategory.LLM)

    def test_can_use_capability_denied_by_prohibited(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.CODING,
            allowed_capabilities=frozenset({"coding.execute_task"}),
            prohibited_capabilities=frozenset({"media.play"}),
        )
        assert not profile.can_use_capability("media.play", CapabilityCategory.TOOL)

    def test_can_use_capability_denied_by_not_allowed(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.CODING,
            allowed_capabilities=frozenset({"coding.execute_task"}),
        )
        assert not profile.can_use_capability("media.play", CapabilityCategory.TOOL)

    def test_can_use_capability_category_filter(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.CODING,
            allowed_categories=frozenset({CapabilityCategory.LLM}),
        )
        assert profile.can_use_capability("chat.respond", CapabilityCategory.LLM)
        assert not profile.can_use_capability("weather.current", CapabilityCategory.TOOL)

    def test_prefers_capability_explicit(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.CODING,
            preferred_capabilities=frozenset({"coding.execute_task"}),
        )
        assert profile.prefers_capability("coding.execute_task", CapabilityCategory.LLM)

    def test_prefers_capability_by_category(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.CODING,
            preferred_categories=frozenset({CapabilityCategory.LLM}),
        )
        assert profile.prefers_capability("chat.respond", CapabilityCategory.LLM)
        assert not profile.prefers_capability("weather.current", CapabilityCategory.TOOL)

    def test_is_specialized_for(self) -> None:
        profile = AgentProfile(
            id="test.agent",
            name="Test Agent",
            specialization=AgentSpecialization.CODING,
            preferred_capabilities=frozenset({"coding.execute_task"}),
        )
        assert profile.is_specialized_for("coding.execute_task", CapabilityCategory.LLM)
        assert not profile.is_specialized_for("media.play", CapabilityCategory.TOOL)