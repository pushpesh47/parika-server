"""
Unit tests for CapabilityResolver.

CapabilityResolver depends on a real CapabilityRegistry to retrieve
capability definitions. Both are exercised against real EventBus and
Logger instances (via the shared `logger`/`event_bus` fixtures);
CapabilityResolver itself has no EventBus dependency and publishes no
events.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_registry.exceptions import (
    CapabilityNotFoundError,
)
from parika.core.capability_resolver.capability_request import (
    CapabilityRequest,
)
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.capability_resolver.exceptions import (
    CapabilityDisabledError,
    CapabilityResolutionError,
)
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@pytest.fixture
def capability_registry(
    event_bus: EventBus,
    logger: Logger,
) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


@pytest.fixture
def capability_resolver(
    capability_registry: CapabilityRegistry,
    logger: Logger,
) -> CapabilityResolver:
    return CapabilityResolver(
        capability_registry=capability_registry,
        logger=logger,
    )


def _make_definition(
    *,
    id: str = "web.search",
    enabled: bool = True,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        id=id,
        name="Web Search",
        description="Search the web.",
        category=CapabilityCategory.TOOL,
        enabled=enabled,
    )


# ---------------------------------------------------------------------
# resolve() - success
# ---------------------------------------------------------------------


class TestResolveSuccess:
    def test_resolves_registered_capability(
        self,
        capability_resolver: CapabilityResolver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        definition = _make_definition()
        capability_registry.register(definition)

        request = CapabilityRequest(capability_id="web.search")
        resolution = capability_resolver.resolve(request)

        assert isinstance(resolution, CapabilityResolution)
        assert resolution.request is request
        assert resolution.definition is definition

    def test_resolution_carries_current_timestamp(
        self,
        capability_resolver: CapabilityResolver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition())

        before = datetime.now(UTC)
        resolution = capability_resolver.resolve(
            CapabilityRequest(capability_id="web.search")
        )
        after = datetime.now(UTC)

        assert before <= resolution.resolved_at <= after

    def test_resolves_using_latest_registry_state(
        self,
        capability_resolver: CapabilityResolver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition(enabled=False))
        capability_registry.enable("web.search")

        resolution = capability_resolver.resolve(
            CapabilityRequest(capability_id="web.search")
        )

        assert resolution.definition.enabled is True

    def test_request_metadata_is_preserved_on_resolution(
        self,
        capability_resolver: CapabilityResolver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition())

        request = CapabilityRequest(
            capability_id="web.search",
            metadata={"trace_id": "abc"},  # type: ignore[arg-type]
        )
        resolution = capability_resolver.resolve(request)

        assert resolution.request.metadata["trace_id"] == "abc"


# ---------------------------------------------------------------------
# resolve() - failure
# ---------------------------------------------------------------------


class TestResolveFailure:
    def test_raises_capability_not_found(
        self,
        capability_resolver: CapabilityResolver,
    ) -> None:
        request = CapabilityRequest(capability_id="unknown.capability")

        with pytest.raises(CapabilityNotFoundError):
            capability_resolver.resolve(request)

    def test_raises_capability_disabled(
        self,
        capability_resolver: CapabilityResolver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition(enabled=False))

        request = CapabilityRequest(capability_id="web.search")

        with pytest.raises(CapabilityDisabledError):
            capability_resolver.resolve(request)

    def test_capability_disabled_is_a_resolution_error(
        self,
        capability_resolver: CapabilityResolver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition(enabled=False))

        request = CapabilityRequest(capability_id="web.search")

        with pytest.raises(CapabilityResolutionError):
            capability_resolver.resolve(request)

    def test_disabled_capability_does_not_produce_resolution(
        self,
        capability_resolver: CapabilityResolver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition(enabled=False))

        try:
            capability_resolver.resolve(
                CapabilityRequest(capability_id="web.search")
            )
        except CapabilityDisabledError as exc:
            assert "web.search" in str(exc)
        else:
            pytest.fail("Expected CapabilityDisabledError to be raised.")


# ---------------------------------------------------------------------
# CapabilityRequest / CapabilityResolution immutability
# ---------------------------------------------------------------------


class TestImmutability:
    def test_request_is_frozen(self) -> None:
        request = CapabilityRequest(capability_id="web.search")

        with pytest.raises(AttributeError):
            request.capability_id = "other"  # type: ignore[misc]

    def test_resolution_is_frozen(
        self,
        capability_resolver: CapabilityResolver,
        capability_registry: CapabilityRegistry,
    ) -> None:
        capability_registry.register(_make_definition())

        resolution = capability_resolver.resolve(
            CapabilityRequest(capability_id="web.search")
        )

        with pytest.raises(AttributeError):
            resolution.resolved_at = datetime.now(UTC)  # type: ignore[misc]

    def test_request_default_metadata_is_empty(self) -> None:
        request = CapabilityRequest(capability_id="web.search")

        assert dict(request.metadata) == {}


# ---------------------------------------------------------------------
# NOTE: CapabilityRequest.metadata was previously not defensively
# copied into an immutable mapping, mirroring the same gap found on
# CapabilityDefinition. This was fixed (capability_request.py) to add
# a __post_init__ freeze, matching every sibling immutable value
# object in the codebase.
# ---------------------------------------------------------------------


class TestMetadataImmutabilityGap:
    def test_metadata_is_defensively_copied(self) -> None:
        mutable_metadata = {"trace_id": "abc"}

        request = CapabilityRequest(
            capability_id="web.search",
            metadata=mutable_metadata,  # type: ignore[arg-type]
        )

        # The request holds its own immutable copy; mutating the
        # original dict afterward does not leak into the request.
        assert request.metadata == {"trace_id": "abc"}
        assert request.metadata is not mutable_metadata

        mutable_metadata["trace_id"] = "mutated"
        assert request.metadata["trace_id"] == "abc"

        with pytest.raises(TypeError):
            request.metadata["trace_id"] = "mutated"  # type: ignore[index]
