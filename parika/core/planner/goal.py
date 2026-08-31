"""
PARIKA Goal

Defines the immutable Goal submitted to Planner.

A Goal represents a single unit of intent that Planner must turn into
an executable PlanStep. Goals may declare dependencies on other Goals
within the same planning request so that Planner can perform
dependency ordering.

Goal decomposition of a high-level user request into individual Goals
is performed by the caller (typically Brain, using AI reasoning).
Planner only organizes, orders, and strategizes already-decomposed
Goals; it does not perform semantic decomposition itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.policy_engine.policy_rule import PolicyRule
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest

ROUTING_GOAL_METADATA_KEY = "is_routing_model_goal"
"""
Optional boolean `Goal.metadata` key. When `True`, this Goal's
Provider model selection is the *routing model* selection -- the
model that receives the outer request, decides tool/capability calls,
and recommends worker models (see `docs/architecture
/Model_Selection_Framework.md` §13.1/§14). It is set only by the one
caller that builds that specific Goal
(`interfaces/ai_context/goal_builder.build_chat_goal()`); every other
Goal (including every nested, Tool-driver-submitted worker Goal) never
sets it, so it defaults to falsy/absent everywhere else.

This is the sole marker Planner reads to decide whether
`[routing_model] mode = "fixed"` may short-circuit straight to a
pinned model for *this* Goal (see `model_selection.routing_strategy
.select_fixed_routing_model()`). It carries no other meaning, is
never read by `build_execution_requirements()` or any `ScoringRule`,
and does not participate in the `execution_requirements` override
shape at all -- it is a plain, independent top-level metadata key.
"""

TERMINAL_SYNTHESIS_GOAL_METADATA_KEY = "is_terminal_synthesis_goal"
"""
Optional boolean `Goal.metadata` key. When `True`, this Goal is the
*terminal synthesis* `chat.respond` goal for the current user request
-- the final response generation that depends on all data-gathering
goals (or the sole `chat.respond` goal for simple requests).

It is set only by `interfaces/session.py` when enhancing decomposed
goals for execution. Planner reads this key alongside
`ROUTING_GOAL_METADATA_KEY` to decide whether `[routing_model]
mode = "fixed"` applies the pinned model to *this* Goal as well
(see `model_selection.routing_strategy.select_fixed_routing_model()`).
Worker Goals and non-synthesis `chat.respond` goals never set it.
"""


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class Goal:
    """
    Immutable unit of intent submitted to Planner.

    A Goal identifies the Capability to invoke together with its
    inputs. Goals may declare dependencies on other Goals within the
    same plan() call through `depends_on`.
    """

    id: str
    """
    Unique identifier of the goal within its planning request.
    """

    capability_id: str
    """
    Identifier of the Capability this goal intends to invoke.
    """

    inputs: Mapping[str, Any] = field(default_factory=dict)
    """
    Input parameters for the invoked Capability.
    """

    context_id: str | None = None
    """
    Optional identifier of the execution Context associated with this
    goal.
    """

    depends_on: tuple[str, ...] = field(default_factory=tuple)
    """
    Identifiers of other Goals, within the same plan() call, that
    must be ordered before this goal.
    """

    policy_rules: tuple[PolicyRule, ...] = field(default_factory=tuple)
    """
    Optional PolicyRule instances evaluated against this goal before
    it is planned. Supplied by the caller; Planner does not store or
    define policies.
    """

    provider_request_builder: (
        Callable[[CapabilityResolution, ProviderModel], ProviderRequest]
        | None
    ) = None
    """
    Optional builder invoked when this goal resolves to a PROVIDER
    execution backend. Required only for capabilities whose category
    maps to an AI provider capability rather than a Tool.

    Planner does not know how to construct concrete, provider-specific
    request payloads; that responsibility belongs to the caller.
    """

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """
    Implementation-neutral metadata carried through to the resulting
    CapabilityExecutionRequest.
    """

    def __post_init__(self) -> None:
        """
        Normalize mutable inputs into immutable equivalents.
        """

        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(dict(self.inputs)),
        )
        object.__setattr__(self, "depends_on", tuple(self.depends_on))
        object.__setattr__(
            self,
            "policy_rules",
            tuple(self.policy_rules),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )
