"""
Capability registry implementation.
"""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .capability_category import CapabilityCategory
from .capability_definition import CapabilityDefinition

from .events import CapabilityDisabled
from .events import CapabilityEnabled
from .events import CapabilityRegistered
from .events import CapabilityUnregistered

from .exceptions import CapabilityAlreadyRegisteredError
from .exceptions import CapabilityNotFoundError
from .exceptions import InvalidCapabilityError


class CapabilityRegistry:
    """
    Central registry for capability definitions.

    The registry stores immutable capability definitions and provides
    lookup operations. It does not execute or resolve capabilities.
    """

    def __init__(self, event_bus: EventBus, logger: Logger) -> None:
        """
        Initialize the capability registry.

        Args:
            event_bus:
                Event bus used to publish registry events.

            logger:
                Logger instance used for diagnostic logging.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()

        self._capabilities: dict[str, CapabilityDefinition] = {}
        self._category_index: dict[CapabilityCategory, set[str]] = {}
        self._tag_index: dict[str, set[str]] = {}

    def _validate_definition(self, definition: CapabilityDefinition) -> None:
        """
        Validate a capability definition.

        Args:
            definition:
                Capability definition to validate.

        Raises:
            InvalidCapabilityError:
                If the definition is invalid.
        """

        if not definition.id.strip():
            raise InvalidCapabilityError(
                "Capability ID cannot be empty."
            )

        if not definition.name.strip():
            raise InvalidCapabilityError(
                "Capability name cannot be empty."
            )

        if type(definition.category) is not CapabilityCategory:
            raise InvalidCapabilityError("Invalid capability category.")

    def register(self, definition: CapabilityDefinition) -> None:
        """
        Register a capability definition.

        Args:
            definition:
                Capability definition to register.

        Raises:
            InvalidCapabilityError:
                If the definition is invalid.

            CapabilityAlreadyRegisteredError:
                If a capability with the same ID already exists.
        """

        with self._lock:
            self._validate_definition(definition)

            if definition.id in self._capabilities:
                raise CapabilityAlreadyRegisteredError(
                    f"Capability '{definition.id}' is already registered."
                )

            self._capabilities[definition.id] = definition

            self._category_index.setdefault(
                definition.category,
                set(),
            ).add(definition.id)

            for tag in definition.tags:
                self._tag_index.setdefault(
                    tag,
                    set(),
                ).add(definition.id)

        self._logger.debug(
            "Registered capability '%s'.",
            definition.id,
        )

        self._event_bus.publish(
            "capability.registered",
            CapabilityRegistered(
                capability_id=definition.id,
            ),
        )

    def unregister(self, capability_id: str) -> None:
        """
        Remove a capability from the registry.

        Args:
            capability_id:
                Identifier of the capability to remove.

        Raises:
            CapabilityNotFoundError:
                If the capability does not exist.
        """

        with self._lock:
            try:
                definition = self._capabilities.pop(capability_id)
            except KeyError as exc:
                raise CapabilityNotFoundError(
                    f"Capability '{capability_id}' was not found."
                ) from exc

            category_ids = self._category_index.get(definition.category)
            if category_ids is not None:
                category_ids.discard(capability_id)

                if not category_ids:
                    del self._category_index[definition.category]

            for tag in definition.tags:
                tag_ids = self._tag_index.get(tag)

                if tag_ids is None:
                    continue

                tag_ids.discard(capability_id)

                if not tag_ids:
                    del self._tag_index[tag]

        self._logger.debug(
            "Unregistered capability '%s'.",
            capability_id,
        )

        self._event_bus.publish(
            "capability.unregistered",
            CapabilityUnregistered(
                capability_id=capability_id,
            ),
        )

    def contains(self, capability_id: str) -> bool:
        """
        Determine whether a capability is registered.

        Args:
            capability_id:
                Capability identifier.

        Returns:
            True if the capability exists; otherwise False.
        """

        return capability_id in self._capabilities

    def get(self, capability_id: str) -> CapabilityDefinition:
        """
        Retrieve a capability definition by its identifier.

        Args:
            capability_id:
                Capability identifier.

        Returns:
            The matching capability definition.

        Raises:
            CapabilityNotFoundError:
                If the capability is not registered.
        """

        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise CapabilityNotFoundError(
                f"Capability '{capability_id}' was not found."
            ) from exc

    def get_all(self) -> tuple[CapabilityDefinition, ...]:
        """
        Retrieve all registered capability definitions.

        Returns:
            A tuple containing all registered capability definitions.
        """

        return tuple(self._capabilities.values())

    def get_by_category(
        self,
        category: CapabilityCategory,
    ) -> tuple[CapabilityDefinition, ...]:
        """
        Retrieve all capabilities belonging to a category.

        Args:
            category:
                Capability category.

        Returns:
            A tuple containing all matching capability definitions.
        """

        capability_ids = self._category_index.get(category, ())

        return tuple(
            self._capabilities[capability_id]
            for capability_id in capability_ids
        )

    def get_by_tag(
        self,
        tag: str,
    ) -> tuple[CapabilityDefinition, ...]:
        """
        Retrieve all capabilities having the specified tag.

        Args:
            tag:
                Capability tag.

        Returns:
            A tuple containing all matching capability definitions.
        """

        capability_ids = self._tag_index.get(tag, ())

        return tuple(
            self._capabilities[capability_id]
            for capability_id in capability_ids
        )

    def find(
        self,
        *,
        category: CapabilityCategory | None = None,
        tag: str | None = None,
        enabled: bool | None = None,
    ) -> tuple[CapabilityDefinition, ...]:
        """
        Find capabilities matching the supplied filters.

        Args:
            category:
                Optional capability category.

            tag:
                Optional capability tag.

            enabled:
                Optional enabled state.

        Returns:
            A tuple containing all matching capability definitions.
        """

        if category is not None:
            definitions = self.get_by_category(category)
        elif tag is not None:
            definitions = self.get_by_tag(tag)
        else:
            definitions = self.get_all()

        if tag is not None:
            definitions = tuple(
                definition
                for definition in definitions
                if tag in definition.tags
            )

        if enabled is not None:
            definitions = tuple(
                definition
                for definition in definitions
                if definition.enabled is enabled
            )

        return definitions

    def enable(self, capability_id: str) -> None:
        """
        Enable a registered capability.

        Args:
            capability_id:
                Capability identifier.

        Raises:
            CapabilityNotFoundError:
                If the capability does not exist.
        """

        with self._lock:
            definition = self.get(capability_id)

            if definition.enabled:
                return

            definition = replace(definition, enabled=True)

            self._capabilities[capability_id] = definition

        self._logger.debug(
            "Enabled capability '%s'.",
            capability_id,
        )

        self._event_bus.publish(
            "capability.enabled",
            CapabilityEnabled(
                capability_id=capability_id,
            ),
        )

    def disable(self, capability_id: str) -> None:
        """
        Disable a registered capability.

        Args:
            capability_id:
                Capability identifier.

        Raises:
            CapabilityNotFoundError:
                If the capability does not exist.
        """

        with self._lock:
            definition = self.get(capability_id)

            if not definition.enabled:
                return

            definition = replace(definition, enabled=False)

            self._capabilities[capability_id] = definition

        self._logger.debug(
            "Disabled capability '%s'.",
            capability_id,
        )

        self._event_bus.publish(
            "capability.disabled",
            CapabilityDisabled(
                capability_id=capability_id,
            ),
        )