"""
Capability resolution service.
"""

from __future__ import annotations

from datetime import UTC, datetime

from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.logger.logger import Logger

from .capability_request import CapabilityRequest
from .capability_resolution import CapabilityResolution
from .exceptions import CapabilityDisabledError


class CapabilityResolver:
    """
    Resolve capability requests into immutable capability resolutions.

    The resolver validates requested capabilities using the
    CapabilityRegistry and produces immutable resolution objects for
    downstream components.
    """

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        logger: Logger,
    ) -> None:
        """
        Initialize the capability resolver.

        Args:
            capability_registry:
                Registry used to retrieve capability definitions.

            logger:
                Logger service used for diagnostic logging.
        """

        self._capability_registry = capability_registry
        self._logger = logger.get_logger(__name__)

    def resolve(
        self,
        request: CapabilityRequest,
    ) -> CapabilityResolution:
        """
        Resolve a capability request.

        Args:
            request:
                Capability request to resolve.

        Returns:
            Immutable capability resolution.

        Raises:
            CapabilityNotFoundError:
                If the requested capability is not registered.

            CapabilityDisabledError:
                If the requested capability is disabled.
        """

        definition = self._capability_registry.get(
            request.capability_id,
        )

        self._validate_definition(definition)

        self._logger.debug(
            "Resolved capability '%s'.",
            request.capability_id,
        )

        return CapabilityResolution(
            request=request,
            definition=definition,
            resolved_at=datetime.now(UTC),
        )

    def _validate_definition(
        self,
        definition: CapabilityDefinition,
    ) -> None:
        """
        Validate a resolved capability definition.

        Args:
            definition:
                Capability definition to validate.

        Raises:
            CapabilityDisabledError:
                If the capability is disabled.
        """

        if definition.enabled:
            return

        raise CapabilityDisabledError(
            f"Capability '{definition.id}' is disabled."
        )