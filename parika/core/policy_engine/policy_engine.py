"""
PARIKA Policy Engine

Provides the core component responsible for evaluating every
policy-driven decision within PARIKA.

PolicyEngine evaluates the PolicyRule instances supplied in a
PolicyEvaluationRequest against an implementation-neutral
PolicyContext, resolves conflicts between matching rules, and produces
an immutable PolicyDecision. PolicyEngine publishes an event for every
evaluation performed.

PolicyEngine does not store policies. The PolicyRule instances
applicable to a given decision are always supplied by the caller,
sourced from wherever policy definitions are owned. PolicyEngine also
does not execute the protected operation a decision applies to;
enforcing a PolicyDecision is the responsibility of the caller.
"""

from __future__ import annotations

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .decision import PolicyDecision
from .events import PolicyEvaluatedEvent
from .exceptions import InvalidPolicyEvaluationRequestError
from .policy_effect import PolicyEffect
from .policy_rule import PolicyRule
from .request import PolicyEvaluationRequest

POLICY_EVALUATED_EVENT = "policy.evaluated"


class PolicyEngine:
    """
    Evaluates every policy-driven decision within PARIKA.

    PolicyEngine is a stateless evaluator. It receives the applicable
    PolicyRule instances together with a PolicyContext on every call,
    resolves conflicts between matching rules, and returns an
    immutable PolicyDecision.

    PolicyEngine intentionally does not:

    - Store policies. Rule definitions are always supplied by the
      caller.
    - Execute protected operations. Enforcement of a PolicyDecision is
      the caller's responsibility.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the PolicyEngine.

        Args:
            event_bus:
                EventBus used to publish evaluation events.

            logger:
                PARIKA Logger component.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def evaluate(
        self,
        request: PolicyEvaluationRequest,
    ) -> PolicyDecision:
        """
        Evaluate a policy request and produce a decision.

        Every rule's predicate is evaluated against the request's
        context. A predicate that raises an exception is treated as
        not matching and is logged; it does not abort the evaluation.

        When multiple rules match, the rule with the highest priority
        wins. Ties are broken in favor of DENY over ALLOW, matching
        the safe default expected of a policy enforcement component.

        Args:
            request:
                Immutable PolicyEvaluationRequest.

        Returns:
            The resolved immutable PolicyDecision.

        Raises:
            InvalidPolicyEvaluationRequestError:
                If `request` is not a PolicyEvaluationRequest.
        """

        if not isinstance(request, PolicyEvaluationRequest):
            raise InvalidPolicyEvaluationRequestError(
                "Expected a PolicyEvaluationRequest instance."
            )

        matched_rules = self._match_rules(request)

        if not matched_rules:
            decision = PolicyDecision(
                effect=request.default_effect,
                matched_rule_id=None,
                reason=None,
            )

        else:
            winner = self._resolve_conflict(matched_rules)

            decision = PolicyDecision(
                effect=winner.effect,
                matched_rule_id=winner.id,
                reason=winner.reason,
            )

        self._event_bus.publish(
            POLICY_EVALUATED_EVENT,
            PolicyEvaluatedEvent(decision=decision),
        )

        self._logger.debug(
            "Policy evaluation resolved to '%s' (matched_rule='%s').",
            decision.effect.value,
            decision.matched_rule_id,
        )

        return decision

    def _match_rules(
        self,
        request: PolicyEvaluationRequest,
    ) -> list[PolicyRule]:
        """
        Determine which supplied rules match the request's context.

        A predicate that raises an exception is logged and treated as
        not matching.
        """

        matched: list[PolicyRule] = []

        for rule in request.rules:

            try:
                matches = rule.predicate(request.context)

            except Exception:
                self._logger.exception(
                    "Policy rule '%s' predicate raised an exception; "
                    "treating as not matched.",
                    rule.id,
                )
                continue

            if matches:
                matched.append(rule)

        return matched

    def _resolve_conflict(
        self,
        matched_rules: list[PolicyRule],
    ) -> PolicyRule:
        """
        Resolve conflicts between multiple matching rules.

        The rule with the highest priority wins. Ties are broken in
        favor of DENY over ALLOW.
        """

        def _sort_key(rule: PolicyRule) -> tuple[int, int]:
            deny_first = 0 if rule.effect is PolicyEffect.DENY else 1
            return (-rule.priority, deny_first)

        return min(matched_rules, key=_sort_key)
