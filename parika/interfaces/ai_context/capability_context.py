"""
PARIKA AI Context Engineering - Capability Context

Owns ONLY discovering which Capabilities currently exist and are
enabled, directly from `CapabilityRegistry` -- with no hardcoded
capability list, and no knowledge of any specific capability's
identity, schema, tool name, or semantics. This is Automatic
Capability Discovery: registering a brand-new Capability requires zero
changes here, and this module never decides how a discovered
Capability should be presented to a model (see `tool_context.py`).

The Capability Catalog (`parika.core.capability_catalog`) is applied
here as a read-only retrieval/ranking pass over the registry's
results: it never adds, removes, executes, or reinterprets a
Capability -- it only narrows and orders the roster the registry
already reports, using each Capability's own generic discovery
metadata (`name`, `description`, `tags`, `aliases`, `keywords`,
`examples`). While the total number of enabled TOOL-category
Capabilities stays within the Catalog's budget (the common case
today), this stage is effectively a no-op and every enabled
Capability is still returned, exactly as before the Catalog existed.
"""

from __future__ import annotations

from parika.core.capability_catalog import CapabilityCatalog
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)

from ..runtime import ParikaRuntime

_default_catalog = CapabilityCatalog()
"""
Module-level default Capability Catalog instance. Stateless and
side-effect free (see `CapabilityCatalog`'s docstring), so a single
shared instance is safe to reuse across every call/turn/session.
"""


def discover_capabilities(
    runtime: ParikaRuntime,
    *,
    text: str = "",
    catalog: CapabilityCatalog | None = None,
) -> tuple[CapabilityDefinition, ...]:
    """
    Return the Capability Catalog's retrieved subset of currently
    enabled TOOL-category Capabilities, discovered live from
    `runtime.capability_registry`.

    Args:
        runtime:
            Runtime whose CapabilityRegistry is queried.

        text:
            The current turn's message text, used only by the
            Capability Catalog's lexical (and, in future, semantic)
            retrieval stages to rank candidates -- never to hardcode
            or special-case any specific Capability.

        catalog:
            Optional `CapabilityCatalog` override; defaults to a
            shared, stateless `CapabilityCatalog()` instance.

    Returns:
        A ranked, budget-limited tuple of enabled TOOL-category
        `CapabilityDefinition`s -- every enabled TOOL-category
        Capability, as long as the total count stays within the
        Catalog's budget.
    """

    definitions = runtime.capability_registry.find(
        category=CapabilityCategory.TOOL,
        enabled=True,
    )

    active_catalog = catalog if catalog is not None else _default_catalog

    return active_catalog.retrieve(definitions, text=text)
