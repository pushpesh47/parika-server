"""
PARIKA AI Context Engineering - Tool Context

Owns ONLY constructing the tool information (native tool-calling
specifications) advertised to the model from already-discovered
Capabilities (see `capability_context.py`), assembling each
Capability's own Tool Affordance Contract into the single
`description` string native tool calling supports, and applying the
two fixed-scope memory-authorization security gates -- the only
filtering AI Context Engineering still performs.

Capability Independence (mandatory): this module owns ZERO
capability-specific knowledge. It never mentions a capability id, a
tool name, or an affordance value by name anywhere in its own code,
and contains no `if capability == ...`/`if tool == ...` branching.
Every fact about a specific Capability's affordances or authorization
requirements is read generically from that Capability's own
`CapabilityDefinition.metadata` -- populated by the Capability's own
Tool/Module, never by this module:

- `metadata["tool_affordance"]` (optional mapping, every key
  optional): the Tool Affordance Contract -- see
  `_AFFORDANCE_SECTION_LABELS` below for the exact keys this module
  understands and how each is rendered. See e.g.
  `parika/tools/weather/manifest.py`'s `WEATHER_TOOL_AFFORDANCES` and
  `parika/modules/weather/driver.py`'s registration.
- `metadata["identity_sensitive"]` (optional bool): whether this
  Capability must never be advertised for a turn recognized as an
  Assistant Identity question. See
  `parika/tools/memory/manifest.py`'s
  `MEMORY_IDENTITY_SENSITIVE_CAPABILITIES` and
  `parika/modules/memory/driver.py`'s registration.
- `metadata["authorization_predicate"]` (optional
  `Callable[[str], bool]`): an opaque, capability-owned check this
  module calls without knowing what it checks or which capability it
  belongs to. See `parika/tools/memory/intent.py`'s
  `has_explicit_memory_intent` and
  `parika/modules/memory/driver.py`'s registration.

Adding a new Capability -- however rich its affordances or
authorization needs -- requires zero changes here: this module already
reads every one of the above generically, and every affordance field
is optional (an absent field simply contributes no section - never an
error, never a fallback that mentions the capability by name). See
`docs/architecture/Request_Understanding.md` for the full dependency
direction:

    Capability -> Capability Metadata -> Tool Affordance Contract
        -> AI Context Engineering -> Prompt -> Brain

`is_identity_query()` (imported below) is not itself capability-
specific knowledge: it is a generic "is this message asking about the
assistant's own identity" text classifier that never mentions any
capability id, tool name, or affordance, and is equally applicable to
any current or future Capability that opts into `identity_sensitive`.
"""

from __future__ import annotations

from typing import Any, Mapping

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.provider_manager.tool_spec import ToolSpec
from parika.tools.memory.identity_guard import is_identity_query

_GENERIC_TOOL_PARAMETERS: Mapping[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}
"""
Permissive fallback JSON Schema used for any enabled Capability that
does not supply its own `metadata["tool_affordance"]["parameters"]` --
this is what makes Automatic Capability Discovery unconditional: a
Capability is always advertisable the moment it is registered and
enabled, whether or not it has yet supplied a curated contract.
"""

_AFFORDANCE_SECTION_LABELS: Mapping[str, str] = {
    "purpose": "Purpose",
    "use_when": "Use when",
    "avoid_when": "Avoid when",
    "requires": "Requires",
    "result_semantics": "Interpreting results",
    "failure_semantics": "On failure",
}
"""
Every Tool Affordance Contract field this module knows how to render,
mapped to the section label it is rendered under, in this fixed
order. Purely a generic rendering contract -- the *values* under each
key are always supplied by the Capability's own Tool, never by this
module. A Capability may omit any subset of these keys; an omitted
key contributes no section, never a placeholder.
"""


def _compose_description(
    affordance: Mapping[str, Any], fallback_description: str
) -> str:
    """
    Compose the single `description` string native tool calling
    supports from `affordance`'s optional fields: a short base
    description (`affordance["description"]`, or `fallback_description`
    when absent) followed by one line per present, non-empty
    `_AFFORDANCE_SECTION_LABELS` key, in that fixed order.

    This is the only place a Capability's Tool Affordance Contract is
    ever assembled into model-facing text -- purely generic string
    formatting keyed by field name, never by which Capability supplied
    the values.
    """

    base = affordance.get("description") or fallback_description

    sections = [
        f"{label}: {affordance[key]}"
        for key, label in _AFFORDANCE_SECTION_LABELS.items()
        if affordance.get(key)
    ]

    if not sections:
        return base

    return base + "\n" + "\n".join(sections)


def _build_tool_spec(definition: CapabilityDefinition) -> ToolSpec:
    """
    Build one provider-independent `ToolSpec` from `definition`,
    reading its optional `metadata["tool_affordance"]` generically --
    never assuming or special-casing which Capability it is.
    """

    affordance = definition.metadata.get("tool_affordance")
    affordance = affordance if isinstance(affordance, Mapping) else {}

    name = affordance.get("name") or definition.id.replace(".", "_")
    description = _compose_description(affordance, definition.description)
    parameters = affordance.get("parameters") or _GENERIC_TOOL_PARAMETERS

    return ToolSpec(
        name=name,
        description=description,
        capability_id=definition.id,
        parameters=parameters,
        implementation=str(definition.metadata.get("implementation", "parika_native")),
        local_only=bool(definition.metadata.get("local_only", False)),
    )


def _is_authorized(
    definition: CapabilityDefinition,
    *,
    text: str,
    is_identity_question: bool,
) -> bool:
    """
    Apply this Capability's own, opaque authorization metadata to the
    current turn. See the module docstring for why this is generic/
    data-driven rather than a hardcoded per-capability check.
    """

    if is_identity_question and definition.metadata.get("identity_sensitive"):
        return False

    predicate = definition.metadata.get("authorization_predicate")

    if predicate is not None and not predicate(text):
        return False

    return True


def discover_tool_specs(
    definitions: tuple[CapabilityDefinition, ...], *, text: str
) -> tuple[ToolSpec, ...]:
    """
    Build the tool specifications to advertise to the chat model from
    `definitions` (typically `capability_context.
    discover_capabilities()`'s result), applying only each
    Capability's own authorization metadata.

    Every Capability in `definitions` is advertised except:

    - Any Capability flagged `identity_sensitive=True` in its own
      metadata, when `text` is recognized as an Assistant Identity
      question.
    - Any Capability whose own `authorization_predicate(text)`
      returns `False`.

    No other filtering happens: relevance judgment for an ordinary
    Capability is left entirely to the model's own native tool-calling
    reasoning over the full roster returned here, guided by each
    Capability's own Tool Affordance Contract (composed into its
    `description` -- see `_compose_description()`) and the general
    Reasoning Policy (`reasoning_policy.py`) -- this is not a
    capability router (see the module docstring).

    Args:
        definitions:
            Capabilities to consider, typically every enabled
            TOOL-category `CapabilityDefinition`.

        text:
            The current turn's message text, passed only to each
            Capability's own authorization metadata -- this function
            itself never inspects `text` for any capability-specific
            wording.

    Returns:
        One `ToolSpec` per authorized Capability in `definitions`.
    """

    is_identity_question = is_identity_query(text, frozenset())

    return tuple(
        _build_tool_spec(definition)
        for definition in definitions
        if _is_authorized(
            definition, text=text, is_identity_question=is_identity_question
        )
    )
