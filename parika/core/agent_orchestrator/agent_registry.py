"""
PARIKA Agent Registry

Extensible registry for agent profiles.
"""

from __future__ import annotations

from collections.abc import Sequence
from threading import RLock
from types import MappingProxyType

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .agent_profile import AgentProfile
from .agent_specialization import AgentSpecialization

from .events import AgentRegistered, AgentUnregistered
from .exceptions import AgentAlreadyRegisteredError, AgentNotFoundError


class AgentRegistry:
    """
    Central registry for agent profiles.
    
    The registry stores immutable agent profiles and provides lookup operations.
    It does not execute or resolve agents directly.
    
    Follows PARIKA's existing registry patterns (CapabilityRegistry, etc.).
    """

    def __init__(self, event_bus: EventBus, logger: Logger) -> None:
        """
        Initialize the agent registry.

        Args:
            event_bus:
                Event bus used to publish registry events.

            logger:
                Logger instance used for diagnostic logging.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()

        self._agents: dict[str, AgentProfile] = {}
        self._specialization_index: dict[AgentSpecialization, set[str]] = {}

    def register(self, profile: AgentProfile) -> None:
        """
        Register an agent profile.

        Args:
            profile:
                Agent profile to register.

        Raises:
            AgentAlreadyRegisteredError:
                If an agent with the same ID already exists.
        """

        with self._lock:
            if profile.id in self._agents:
                raise AgentAlreadyRegisteredError(
                    f"Agent '{profile.id}' is already registered."
                )

            self._agents[profile.id] = profile

            self._specialization_index.setdefault(
                profile.specialization,
                set(),
            ).add(profile.id)

        self._logger.debug(
            "Registered agent '%s' (specialization: %s).",
            profile.id,
            profile.specialization.value,
        )

        self._event_bus.publish(
            "agent.registered",
            AgentRegistered(agent_id=profile.id, specialization=profile.specialization.value),
        )

    def unregister(self, agent_id: str) -> None:
        """
        Remove an agent from the registry.

        Args:
            agent_id:
                Identifier of the agent to remove.

        Raises:
            AgentNotFoundError:
                If the agent does not exist.
        """

        with self._lock:
            try:
                profile = self._agents.pop(agent_id)
            except KeyError as exc:
                raise AgentNotFoundError(
                    f"Agent '{agent_id}' was not found."
                ) from exc

            specialization_ids = self._specialization_index.get(profile.specialization)
            if specialization_ids is not None:
                specialization_ids.discard(agent_id)

                if not specialization_ids:
                    del self._specialization_index[profile.specialization]

        self._logger.debug(
            "Unregistered agent '%s'.",
            agent_id,
        )

        self._event_bus.publish(
            "agent.unregistered",
            AgentUnregistered(agent_id=agent_id),
        )

    def contains(self, agent_id: str) -> bool:
        """
        Determine whether an agent is registered.

        Args:
            agent_id:
                Agent identifier.

        Returns:
            True if the agent exists; otherwise False.
        """

        return agent_id in self._agents

    def get(self, agent_id: str) -> AgentProfile:
        """
        Retrieve an agent profile by its identifier.

        Args:
            agent_id:
                Agent identifier.

        Returns:
            The matching agent profile.

        Raises:
            AgentNotFoundError:
                If the agent is not registered.
        """

        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise AgentNotFoundError(
                f"Agent '{agent_id}' was not found."
            ) from exc

    def get_all(self) -> tuple[AgentProfile, ...]:
        """
        Retrieve all registered agent profiles.

        Returns:
            A tuple containing all registered agent profiles.
        """

        return tuple(self._agents.values())

    def get_by_specialization(
        self,
        specialization: AgentSpecialization,
    ) -> tuple[AgentProfile, ...]:
        """
        Retrieve all agents belonging to a specialization.

        Args:
            specialization:
                Agent specialization.

        Returns:
            A tuple containing all matching agent profiles.
        """

        agent_ids = self._specialization_index.get(specialization, ())

        return tuple(
            self._agents[agent_id]
            for agent_id in agent_ids
        )

    def find(
        self,
        *,
        specialization: AgentSpecialization | None = None,
        capability_id: str | None = None,
        category: str | None = None,
    ) -> tuple[AgentProfile, ...]:
        """
        Find agents matching the supplied filters.

        Args:
            specialization:
                Optional agent specialization.

            capability_id:
                Optional capability ID to match against allowed capabilities.

            category:
                Optional capability category to match against allowed categories.

        Returns:
            A tuple containing all matching agent profiles.
        """

        if specialization is not None:
            profiles = self.get_by_specialization(specialization)
        else:
            profiles = self.get_all()

        if capability_id is not None:
            profiles = tuple(
                profile
                for profile in profiles
                if capability_id in profile.allowed_capabilities
            )

        if category is not None:
            profiles = tuple(
                profile
                for profile in profiles
                if category in profile.allowed_categories
            )

        return profiles