"""
Unit tests for PolicyEngine.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.policy_engine.decision import PolicyDecision
from parika.core.policy_engine.events import PolicyEvaluatedEvent
from parika.core.policy_engine.exceptions import (
    InvalidPolicyEvaluationRequestError,
)
from parika.core.policy_engine.policy_effect import PolicyEffect
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.policy_engine.policy_rule import PolicyRule
from parika.core.policy_engine.request import PolicyEvaluationRequest


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(logger=_FakeLogger())  # type: ignore[arg-type]


@pytest.fixture
def policy_engine(event_bus: EventBus) -> PolicyEngine:
    return PolicyEngine(event_bus=event_bus, logger=_FakeLogger())  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# Basic evaluation
# ---------------------------------------------------------------------


class TestEvaluate:
    def test_rejects_invalid_request(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        with pytest.raises(InvalidPolicyEvaluationRequestError):
            policy_engine.evaluate(object())  # type: ignore[arg-type]

    def test_returns_default_effect_when_no_rules_match(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        request = PolicyEvaluationRequest(
            rules=(),
            context={},
            default_effect=PolicyEffect.ALLOW,
        )

        decision = policy_engine.evaluate(request)

        assert decision.effect is PolicyEffect.ALLOW
        assert decision.matched_rule_id is None
        assert decision.is_allowed

    def test_default_effect_can_be_deny(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        request = PolicyEvaluationRequest(
            rules=(),
            context={},
            default_effect=PolicyEffect.DENY,
        )

        decision = policy_engine.evaluate(request)

        assert decision.effect is PolicyEffect.DENY
        assert not decision.is_allowed

    def test_matching_rule_determines_decision(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        rule = PolicyRule(
            id="deny-internet-when-offline",
            effect=PolicyEffect.DENY,
            predicate=lambda ctx: ctx.get("requires_internet") is True,
            reason="Internet access is restricted.",
        )

        request = PolicyEvaluationRequest(
            rules=(rule,),
            context={"requires_internet": True},
        )

        decision = policy_engine.evaluate(request)

        assert decision.effect is PolicyEffect.DENY
        assert decision.matched_rule_id == "deny-internet-when-offline"
        assert decision.reason == "Internet access is restricted."

    def test_non_matching_rule_falls_back_to_default(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        rule = PolicyRule(
            id="deny-internet-when-offline",
            effect=PolicyEffect.DENY,
            predicate=lambda ctx: ctx.get("requires_internet") is True,
        )

        request = PolicyEvaluationRequest(
            rules=(rule,),
            context={"requires_internet": False},
            default_effect=PolicyEffect.ALLOW,
        )

        decision = policy_engine.evaluate(request)

        assert decision.effect is PolicyEffect.ALLOW
        assert decision.matched_rule_id is None

    def test_publishes_evaluated_event(
        self,
        policy_engine: PolicyEngine,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("policy.evaluated", subscriber)

        request = PolicyEvaluationRequest(rules=(), context={})
        decision = policy_engine.evaluate(request)

        assert len(subscriber.received) == 1
        event = subscriber.received[0]
        assert isinstance(event, PolicyEvaluatedEvent)
        assert event.decision == decision

    def test_decision_is_immutable(self) -> None:
        decision = PolicyDecision(
            effect=PolicyEffect.ALLOW,
            matched_rule_id=None,
        )

        with pytest.raises(AttributeError):
            decision.effect = PolicyEffect.DENY  # type: ignore[misc]


# ---------------------------------------------------------------------
# Robustness of rule execution
# ---------------------------------------------------------------------


class TestRuleExecutionRobustness:
    def test_predicate_exception_is_treated_as_not_matched(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        def _boom(context: Any) -> bool:
            raise RuntimeError("boom")

        broken_rule = PolicyRule(
            id="broken",
            effect=PolicyEffect.DENY,
            predicate=_boom,
        )

        request = PolicyEvaluationRequest(
            rules=(broken_rule,),
            context={},
            default_effect=PolicyEffect.ALLOW,
        )

        # Should not raise despite the broken predicate.
        decision = policy_engine.evaluate(request)

        assert decision.effect is PolicyEffect.ALLOW
        assert decision.matched_rule_id is None

    def test_broken_rule_does_not_prevent_other_rules_from_matching(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        def _boom(context: Any) -> bool:
            raise RuntimeError("boom")

        broken_rule = PolicyRule(
            id="broken",
            effect=PolicyEffect.ALLOW,
            predicate=_boom,
        )
        working_rule = PolicyRule(
            id="working",
            effect=PolicyEffect.DENY,
            predicate=lambda ctx: True,
        )

        request = PolicyEvaluationRequest(
            rules=(broken_rule, working_rule),
            context={},
        )

        decision = policy_engine.evaluate(request)

        assert decision.matched_rule_id == "working"


# ---------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------


class TestConflictResolution:
    def test_higher_priority_rule_wins(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        low_priority_allow = PolicyRule(
            id="low-allow",
            effect=PolicyEffect.ALLOW,
            predicate=lambda ctx: True,
            priority=1,
        )
        high_priority_deny = PolicyRule(
            id="high-deny",
            effect=PolicyEffect.DENY,
            predicate=lambda ctx: True,
            priority=10,
        )

        request = PolicyEvaluationRequest(
            rules=(low_priority_allow, high_priority_deny),
            context={},
        )

        decision = policy_engine.evaluate(request)

        assert decision.matched_rule_id == "high-deny"
        assert decision.effect is PolicyEffect.DENY

    def test_deny_wins_tie_on_priority(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        allow_rule = PolicyRule(
            id="allow",
            effect=PolicyEffect.ALLOW,
            predicate=lambda ctx: True,
            priority=5,
        )
        deny_rule = PolicyRule(
            id="deny",
            effect=PolicyEffect.DENY,
            predicate=lambda ctx: True,
            priority=5,
        )

        request = PolicyEvaluationRequest(
            rules=(allow_rule, deny_rule),
            context={},
        )

        decision = policy_engine.evaluate(request)

        assert decision.effect is PolicyEffect.DENY
        assert decision.matched_rule_id == "deny"

    def test_conflict_resolution_is_order_independent(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        allow_rule = PolicyRule(
            id="allow",
            effect=PolicyEffect.ALLOW,
            predicate=lambda ctx: True,
            priority=5,
        )
        deny_rule = PolicyRule(
            id="deny",
            effect=PolicyEffect.DENY,
            predicate=lambda ctx: True,
            priority=5,
        )

        request = PolicyEvaluationRequest(
            rules=(deny_rule, allow_rule),
            context={},
        )

        decision = policy_engine.evaluate(request)

        assert decision.matched_rule_id == "deny"


# ---------------------------------------------------------------------
# Request immutability
# ---------------------------------------------------------------------


class TestRequestImmutability:
    def test_context_is_defensively_copied(
        self,
        policy_engine: PolicyEngine,
    ) -> None:
        mutable_context = {"requires_internet": True}
        request = PolicyEvaluationRequest(
            rules=(),
            context=mutable_context,
        )

        mutable_context["requires_internet"] = False

        assert request.context["requires_internet"] is True

    def test_rules_are_normalized_to_tuple(self) -> None:
        rule = PolicyRule(
            id="a",
            effect=PolicyEffect.ALLOW,
            predicate=lambda ctx: True,
        )

        request = PolicyEvaluationRequest(rules=[rule], context={})

        assert isinstance(request.rules, tuple)
